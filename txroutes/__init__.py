import logging

import routes
from twisted.internet.defer import Deferred, inlineCallbacks
from twisted.web.resource import Resource
from twisted.web.server import NOT_DONE_YET
from twisted.python.failure import Failure
from twisted.python.log import logging

DEFAULT_404_HTML = '<html><head><title>404 Not Found</title></head>' \
        '<body><h1>Not found</h1></body></html>'

DEFAULT_500_HTML = '<html><head><title>500 Internal Server Error</title>' \
        '</head><body><h1>Internal Server Error</h1></body></html>'



class Dispatcher(Resource):
    '''
    Provides routes-like dispatching for twisted.web.server.

    Frequently, it's much easier to describe your website layout using routes
    instead of Resource from twisted.web.resource. This small library lets you
    dispatch with routes in your twisted.web application. It also handles some
    of the bookkeeping with deferreds, so you don't have to return NOT_DONE_YET
    yourself.

    Usage:

        from twisted.internet import defer, reactor, task
        from twisted.web.server import Site

        from txroutes import Dispatcher


        # Create a Controller
        class Controller(object):

            def index(self, request):
                return '<html><body>Hello World!</body></html>'

            def docs(self, request, item):
                return '<html><body>Docs for %s</body></html>' % item.encode('utf8')

            def post_data(self, request):
                return '<html><body>OK</body></html>'

            @defer.inlineCallbacks
            def deferred_example(self, request):
                request.write('<html><body>Wait a tic...</body></html>')
                yield task.deferLater(reactor, 5, lambda: request.finish())

        c = Controller()

        dispatcher = Dispatcher()

        dispatcher.connect(name='index', route='/', controller=c, action='index')

        dispatcher.connect(name='docs', route='/docs/{item}', controller=c,
                action='docs')

        dispatcher.connect(name='data', route='/data', controller=c,
                action='post_data', conditions=dict(method=['POST']))

        dispatcher.connect(name='deferred_example', route='/wait', controller=c,
                action='deferred_example')

        factory = Site(dispatcher)
        reactor.listenTCP(8000, factory)
        reactor.run()

    Helpful background information:
    - Python routes: http://routes.groovie.org/
    - Using twisted.web.resources: http://twistedmatrix.com/documents/current/web/howto/web-in-60/dynamic-dispatch.html
    '''

    def __init__(self, logger=logging.getLogger('txroutes')):
        Resource.__init__(self)

        self.__controllers = {}
        self.__mapper = routes.Mapper()
        self.__logger = logger

    def connect(self, name, route, controller, **kwargs):
        self.__controllers[name] = controller
        self.__mapper.connect(name, route, controller=name, **kwargs)

    def getChild(self, name, request):
        return self

    def render(self, request):

        wsgi_environ = {}
        wsgi_environ['REQUEST_METHOD'] = request.method
        wsgi_environ['PATH_INFO'] = request.path

        result = self.__mapper.match(environ=wsgi_environ)

        handler = self._render_404

        if result is not None:
            controller = result.get('controller', None)
            controller = self.__controllers.get(controller)

            if controller is not None:
                del result['controller']
                action = result.get('action', None)

                if action is not None:
                    del result['action']
                    func = getattr(controller, action, None)
                    if func:
                        handler = lambda request: func(request, **result)

        render = self.__execute_handler(request, handler)
        render.addErrback(self.__execute_failure, request)

        return NOT_DONE_YET

    # Subclasses can override with their own 404 rendering.
    def _render_404(self, request):
        request.setResponseCode(404)
        return DEFAULT_404_HTML

    # Subclasses can override with their own failure rendering.
    def _render_failure(self, request, failure):
        self.__logger.error(failure.getTraceback())
        request.setResponseCode(500)
        return DEFAULT_500_HTML

    @inlineCallbacks
    def __execute_handler(self, request, handler):

        # Detect the content and whether the request is complete based
        # on what the handler returns.
        content = None
        complete = False
        response = handler(request)

        if isinstance(response, Deferred):
            content = yield response
            complete = True

        elif response is NOT_DONE_YET:
            content = None
            complete = False

        else:
            content = response
            complete = True

        # If this response is complete, but the request has not been
        # finished yet, ensure finish is called.
        if complete and not request.finished:
            if content:
                request.write(content)
            request.finish()

    def __execute_failure(self, failure, request):

        # If the subclass overrode the deprecated _render_error code, execute
        # it but log a deprecation warning.
        if hasattr(self, '_render_error'):
            self.__logger.warning('_render_error in txroutes.Dispatcher is deprecated, please override _render_failure instead')
            handler = lambda request: self._render_error(request, failure=failure)
        else:
            handler = lambda request: self._render_failure(request, failure)

        # Render the failure, falling back to the default failure renderer
        # if an error occurs in _render_failure itself.
        render = self.__execute_handler(request, handler)
        render.addErrback(self.__execute_default_failure, request)

    def __execute_default_failure(self, failure, request):

        # Use default failure rendering when a subclass override of
        # _render_failure itself raised an unhandled error.
        try:
            self.__logger.error(failure.getTraceback())
            if not request.finished:
                request.setResponseCode(500)
                request.write(DEFAULT_500_HTML)
                request.finish()
        except Exception as e:
            self.__logger.exception(e)


if __name__ == '__main__':
    import logging

    import twisted.python.log
    from twisted.internet import defer, reactor, task
    from twisted.web.server import Site

    # Set up logging
    log = logging.getLogger('txroutes')
    log.setLevel(logging.INFO)

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    log.addHandler(handler)

    observer = twisted.python.log.PythonLoggingObserver(loggerName='txroutes')
    observer.start()

    # Create a Controller
    class Controller(object):

        def index(self, request):
            return '<html><body>Hello World!</body></html>'

        def docs(self, request, item):
            return '<html><body>Docs for %s</body></html>' % item.encode('utf8')

        def post_data(self, request):
            return '<html><body>OK</body></html>'

        @defer.inlineCallbacks
        def deferred_example(self, request):
            request.write('<html><body>Wait a tic...</body></html>')
            yield task.deferLater(reactor, 5, lambda: request.finish())

    c = Controller()

    dispatcher = Dispatcher(log)

    dispatcher.connect(name='index', route='/', controller=c, action='index')

    dispatcher.connect(name='docs', route='/docs/{item}', controller=c,
            action='docs')

    dispatcher.connect(name='data', route='/data', controller=c,
            action='post_data', conditions=dict(method=['POST']))

    dispatcher.connect(name='deferred_example', route='/wait', controller=c,
            action='deferred_example')

    factory = Site(dispatcher)
    reactor.listenTCP(8000, factory)
    reactor.run()
