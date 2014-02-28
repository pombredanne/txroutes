import routes
from twisted.internet.defer import Deferred, inlineCallbacks
from twisted.web.resource import Resource
from twisted.web.server import NOT_DONE_YET
from twisted.python.failure import Failure

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

    def __init__(self):
        Resource.__init__(self)

        self.__controllers = {}
        self.__mapper = routes.Mapper()

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

        handler = None

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

        try:
            handler = handler or self._render_404
            self.__detect_and_execute_handler(request, handler)
            return NOT_DONE_YET

        except Exception, e:
            try:
                self._log_exception(request, e)
            finally:
                handler = self._render_500
                self.__detect_and_execute_handler(request, handler)
                return NOT_DONE_YET

    # Subclasses can override with their own logging.
    def _log_failure(self, request, failure):
        pass

    # Subclasses can override with their own logging.
    def _log_exception(self, request, exception):
        pass

    # Subclasses can override with their own exception rendering.
    def _render_exception(self, request, exception):
        request.setResponseCode(500)
        return '<html><head><title>500 Internal Server Error</title></head>' \
                '<body><h1>Internal Server Error</h1></body></html>'

    # Subclasses can override with their own 404 rendering.
    def _render_404(self, request):
        request.setResponseCode(404)
        return '<html><head><title>404 Not Found</title></head>' \
                '<body><h1>Not found</h1></body></html>'

    @inlineCallbacks
    def __detect_and_execute_handler(self, request, handler, raise_exceptions=False):

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
            if raise_exceptions:
                raise

            # Allow subclasses to override logging for these exceptions.
            # When using inlineCallbacks, logger.exception() does not show the
            # real traceback. We need log failure.getTraceback() to show that.
            # Use Failure._findFailure() to get the failure associated
            # with this exception.
            try:
                try:
                    failure = Failure._findFailure()
                except Exception:
                    failure = None

                if failure:
                    self._log_failure(request, failure)
                else:
                    self._log_exception(request, e)

            # After attempting to log the exception, always render the exception
            # and prevent infinite recursion by making sure this recursive
            # invocation simply throws on the next time through.
            finally:
                handler = lambda request: self._render_exception(request, e)
                yield self.__detect_and_execute_handler(request, handler,
                        raise_exceptions=True)


if __name__ == '__main__':
    import logging

    import twisted.python.log
    from twisted.internet import defer, reactor, task
    from twisted.web.server import Site

    # Set up logging
    log = logging.getLogger('twisted_routes')
    log.setLevel(logging.INFO)

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    log.addHandler(handler)

    observer = twisted.python.log.PythonLoggingObserver(loggerName='twisted_routes')
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
