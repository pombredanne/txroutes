import logging

import routes
from twisted.internet.defer import Deferred, inlineCallbacks
from twisted.web.resource import Resource
from twisted.web.server import NOT_DONE_YET
from twisted.python.failure import Failure
from twisted.python.log import logging


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

        self.__detect_and_execute_handler(request, handler)
        return NOT_DONE_YET

    # Subclasses can override with their own 404 rendering.
    def _render_404(self, request):
        request.setResponseCode(404)
        return '<html><head><title>404 Not Found</title></head>' \
                '<body><h1>Not found</h1></body></html>'

    # Subclasses can override with their own error rendering.
    def _render_error(self, request, exception=None, failure=None):
        return self.__render_default_error(request, exception, failure)

    def __render_default_error(self, request, exception=None, failure=None):
        if failure:
            self.__logger.error(failure.getTraceback())
        else:
            self.__logger.exception(exception)
        request.setResponseCode(500)
        return '<html><head><title>500 Internal Server Error</title></head>' \
                '<body><h1>Internal Server Error</h1></body></html>'

    @inlineCallbacks
    def __detect_and_execute_handler(self, request, handler, use_default_error_rendering=False):

        # Detect the content and whether the request is complete based
        # on what the handler returns.
        try:
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

        except Exception, e:

            # When using inlineCallbacks, logger.exception() does not show the
            # real traceback. Subclasses will need log failure.getTraceback()
            # to show tracebacks. Use Failure._findFailure() to get the failure
            # associated with this exception.
            failure = None
            try:
                failure = Failure._findFailure()
            except Exception:
                failure = None

            # Use default error rendering when a subclass override of
            # _render_error itself raised an unhandled error.
            if use_default_error_rendering:
                self.__render_default_error(request, e, failure)

            # Otherwise, render the error and finish the request. Prevent
            # infinite recursion by ensuring this recursive invocation falls
            # back to __render_default_error.
            else:
                handler = lambda request: self._render_error(request, e, failure)
                yield self.__detect_and_execute_handler(request, handler,
                        use_default_error_rendering=True)


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
