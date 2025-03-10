# This software was developed by employees of the National Institute of
# Standards and Technology (NIST), an agency of the Federal Government.
# Pursuant to title 17 United States Code Section 105, works of NIST employees
# are not subject to copyright protection in the United States and are
# considered to be in the public domain. Permission to freely use, copy,
# modify, and distribute this software and its documentation without fee is
# hereby granted, provided that this notice and disclaimer of warranty appears
# in all copies.
#
# THE SOFTWARE IS PROVIDED 'AS IS' WITHOUT ANY WARRANTY OF ANY KIND, EITHER
# EXPRESSED, IMPLIED, OR STATUTORY, INCLUDING, BUT NOT LIMITED TO, ANY WARRANTY
# THAT THE SOFTWARE WILL CONFORM TO SPECIFICATIONS, ANY IMPLIED WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND FREEDOM FROM
# INFRINGEMENT, AND ANY WARRANTY THAT THE DOCUMENTATION WILL CONFORM TO THE
# SOFTWARE, OR ANY WARRANTY THAT THE SOFTWARE WILL BE ERROR FREE. IN NO EVENT
# SHALL NIST BE LIABLE FOR ANY DAMAGES, INCLUDING, BUT NOT LIMITED TO, DIRECT,
# INDIRECT, SPECIAL OR CONSEQUENTIAL DAMAGES, ARISING OUT OF, RESULTING FROM,
# OR IN ANY WAY CONNECTED WITH THIS SOFTWARE, WHETHER OR NOT BASED UPON
# WARRANTY, CONTRACT, TORT, OR OTHERWISE, WHETHER OR NOT INJURY WAS SUSTAINED
# BY PERSONS OR PROPERTY OR OTHERWISE, AND WHETHER OR NOT LOSS WAS SUSTAINED
# FROM, OR AROSE OUT OF THE RESULTS OF, OR USE OF, THE SOFTWARE OR SERVICES
# PROVIDED HEREUNDER. Distributions of NIST software should also include
# copyright and licensing statements of any third-party software that are
# legally bundled with the code in compliance with the conditions of those
# licenses.

__all__ = [  # "misc"
    "ConfigStore",
    "hash_caller",
    "kill_by_name",
    "show_messages",
    "logger",
    "LabbenchDeprecationWarning",
    "import_t0",
    # concurrency and sequencing
    "concurrently",
    "sequentially",
    "Call",
    "ConcurrentException",
    "check_hanging_thread",
    "ThreadSandbox",
    "ThreadEndedByMaster",
    # timing and flow management
    "retry",
    "until_timeout",
    "sleep",
    "stopwatch",
    "timeout_iter"
    # wrapper helpers
    "copy_func",
    # traceback scrubbing
    "hide_in_traceback",
    "_force_full_traceback",
    # helper objects
    "Ownable",
]

from contextlib import contextmanager, _GeneratorContextManager
from functools import wraps
from queue import Queue, Empty
from threading import Thread, ThreadError, Event
from typing import Callable

import builtins
import hashlib
import inspect
import logging
import psutil
import sys
import time
import traceback
from warnings import simplefilter

import_t0 = time.perf_counter()

logger = logging.LoggerAdapter(
    logging.getLogger("labbench"),
    dict(
        label="labbench"
    ),  # description of origin within labbench (for screen logs only)
)

# show deprecation warnings only once
class LabbenchDeprecationWarning(DeprecationWarning):
    pass


simplefilter("once", LabbenchDeprecationWarning)
import weakref


def show_messages(minimum_level, colors=True):
    """Configure screen debug message output for any messages as least as important as indicated by `level`.

    Arguments:
        minimum_level: One of 'debug', 'warning', 'error', or None. If None, there will be no output.
    Returns:
        None
    """

    import logging

    err_map = {
        "debug": logging.DEBUG,
        "warning": logging.WARNING,
        "error": logging.ERROR,
        "info": logging.INFO,
        None: None,
    }

    if minimum_level not in err_map and not isinstance(minimum_level, int):
        raise ValueError(
            f"message level must be a flag {tuple(err_map.keys())} or an integer, not {repr(minimum_level)}"
        )

    level = (
        err_map[minimum_level.lower()]
        if isinstance(minimum_level, str)
        else minimum_level
    )

    logger.setLevel(level)

    # Clear out any stale handlers
    if hasattr(logger, "_screen_handler"):
        logger.logger.removeHandler(logger._screen_handler)

    if level is None:
        return

    logger._screen_handler = logging.StreamHandler()
    logger._screen_handler.setLevel(level)
    # - %(pathname)s:%(lineno)d'

    if colors:
        from coloredlogs import ColoredFormatter, DEFAULT_FIELD_STYLES

        log_fmt = "{levelname:^7s} {asctime}.{msecs:03.0f} • {label}: {message}"
        styles = dict(DEFAULT_FIELD_STYLES, label=dict(color="blue"),)
        formatter = ColoredFormatter(log_fmt, style="{", field_styles=styles)
    else:
        log_fmt = "{levelname:^7s} {asctime}.{msecs:03.0f} • {label}: {message}"
        formatter = logging.Formatter(log_fmt, style="{")

    logger._screen_handler.setFormatter(formatter)
    logger.logger.addHandler(logger._screen_handler)


show_messages("info")


def _inject_logger_metadata(obj):
    d = dict(
        object=repr(obj), origin=type(obj).__qualname__, owned_name=obj._owned_name,
    )  

    if d["owned_name"] is not None:
        d["label"] = d["owned_name"]
    elif repr(obj) == object.__repr__(obj):
        d["label"] = type(obj).__qualname__ + "(...)"
    else:
        txt = repr(obj)
        if len(txt) > 20:
            txt = txt[:-1].split(",")[0] + ")"
        d["label"] = txt

    return d


def callable_logger(func):
    if isinstance(getattr(func, "__self__", None), Ownable):
        return func.__self__._logger
    else:
        return logger


class Ownable:
    """Subclass to pull in name from an owning class."""

    __objclass__ = None
    _owned_name = None
    _logger = logger

    def __init__(self):
        self._logger = logging.LoggerAdapter(
            logger.logger, extra=_inject_logger_metadata(self),
        )

    def __set_name__(self, owner_cls, name):
        self.__objclass__ = owner_cls
        self.__name__ = name

    def __get__(self, owner, owner_cls=None):
        return self

    def __owner_init__(self, owner):
        """called on instantiation of the owner (again for its parent owner)"""
        if owner._owned_name is None:
            self._owned_name = self.__name__
        else:
            self._owned_name = owner._owned_name + "." + self.__name__

        self._logger.extra.update(**_inject_logger_metadata(self))

    def __owner_subclass__(self, owner_cls):
        """Called after the owner class is instantiated; returns an object to be used in the Rack namespace"""
        # TODO: revisit whether there should be any assignment of _owned_name here
        if self._owned_name is None:
            self._owned_name = self.__name__

        return self

    def __repr__(self):
        if self.__objclass__ is not None:
            cls = type(self)
            ownercls = self.__objclass__

            typename = cls.__module__ + "." + cls.__name__
            ownedname = ownercls.__qualname__
            return f"<{typename} object at {hex(id(self))} bound to {ownedname} class at {hex(id(ownercls))}>"

        else:
            return object.__repr__(self)

    def __str__(self):
        return self._owned_name or repr(self)


class ConcurrentException(Exception):
    """Raised on concurrency errors in `labbench.concurrently`"""

    thread_exceptions = []


class OwnerThreadException(ThreadError):
    """Raised to encapsulate a thread raised by the owning thread during calls to `labbench.concurrently`"""


class ThreadEndedByMaster(ThreadError):
    """Raised in a thread to indicate the owning thread requested termination"""


concurrency_count = 0
stop_request_event = Event()

sys._debug_tb = False

import types

TRACEBACK_HIDE_TAG = "🦙 hide from traceback 🦙"


def hide_in_traceback(func):
    def adjust(f):
        code = f.__code__

        if tuple(sys.version_info)[:2] >= (3, 8):
            f.__code__ = code.replace(co_consts=code.co_consts + (TRACEBACK_HIDE_TAG,))
        else:
            # python < 3.8
            f.__code__ = types.CodeType(
                code.co_argcount,
                code.co_kwonlyargcount,
                code.co_nlocals,
                code.co_stacksize,
                code.co_flags,
                code.co_code,
                code.co_consts + (TRACEBACK_HIDE_TAG,),
                code.co_names,
                code.co_varnames,
                code.co_filename,
                code.co_name,
                code.co_firstlineno,
                code.co_lnotab,
                code.co_freevars,
                code.co_cellvars,
            )

    if not callable(func):
        raise TypeError(f"{func} is not callable")

    if hasattr(func, "__code__"):
        adjust(func)
    if hasattr(func.__call__, "__code__"):
        adjust(func.__call__)

    return func


def _force_full_traceback(force: bool):
    sys._debug_tb = force


class _filtered_exc_info:
    """a monkeypatch for sys.exc_info that removes functions from tracebacks
    that are tagged with TRACEBACK_HIDE_TAG
    """

    def __init__(self, wrapped):
        self.lb_wrapped = wrapped

    def __call__(self):
        try:
            etype, evalue, start_tb = self.lb_wrapped()

            if sys._debug_tb:
                return etype, evalue, start_tb

            tb = prev_tb = start_tb

            # step through the stack traces
            while tb is not None:
                if TRACEBACK_HIDE_TAG in tb.tb_frame.f_code.co_consts:
                    # when the tag is present, change the previous tb_next to skip this tb
                    if tb is start_tb:
                        start_tb = start_tb.tb_next
                    else:
                        prev_tb.tb_next = tb.tb_next

                # on to the next traceback
                prev_tb, tb = tb, tb.tb_next

            return etype, evalue, start_tb

        except BaseException as e:
            raise


def copy_func(
    func,
    assigned=("__module__", "__name__", "__qualname__", "__doc__", "__annotations__"),
    updated=("__dict__",),
) -> callable:
    """returns a copy of func with specified attributes (following the inspect.wraps arguments).

    This is similar to wrapping `func` with `lambda *args, **kws: func(*args, **kws)`, except
    the returned callable contains a duplicate of the bytecode in `func`. The idea that the
    returned copy has fresh to __doc__, __signature__, etc., which can be changed without
    independently of `func`.
    """

    new = types.FunctionType(
        func.__code__,
        func.__globals__,
        func.__name__,
        func.__defaults__,
        func.__closure__,
    )

    for attr in assigned:
        setattr(new, attr, getattr(func, attr))

    for attr in updated:
        getattr(new, attr).update(getattr(func, attr))

    return new


# TODO: remove this
def withsignature(
    cls,
    name: str,
    fields: list,
    defaults: dict,
    positional: int = None,
    annotations: dict = {},
):
    """Replace cls.__init__ with a wrapper function with an explicit
    call signature, replacing the actual call signature that can be
    dynamic __init__(self, *args, **kws) call signature.

    :fields: iterable of names of each call signature argument
    :
    """
    # Is the existing cls.__init__ already a __init__ wrapper?
    wrapped = getattr(cls, name)
    orig_doc = getattr(wrapped, "__origdoc__", cls.__init__.__doc__)
    reuse = hasattr(wrapped, "__dynamic__")

    defaults = tuple(defaults.items())

    if positional is None:
        positional = len(fields)

    # Generate a code object with the adjusted signature
    code = wrapper.__code__

    if tuple(sys.version_info)[:2] >= (3, 8):
        # there is a new co_posonlyargs argument since 3.8 - use the new .replace
        # to be less brittle to future signature changes
        code = code.replace(
            co_argcount=1 + positional,  # to include self
            co_posonlyargcount=0,
            co_kwonlyargcount=len(fields) - positional,
            co_nlocals=len(fields) + 1,  # to include self
            co_varnames=("self",) + tuple(fields),
        )
    else:
        code = types.CodeType(
            1 + positional,  # co_argcount
            len(fields) - positional,  # co_kwonlyargcount
            len(fields) + 1,  # co_nlocals
            code.co_stacksize,
            code.co_flags,
            code.co_code,
            code.co_consts,
            code.co_names,
            ("self",) + tuple(fields),  # co_varnames
            code.co_filename,
            code.co_name,
            code.co_firstlineno,
            code.co_lnotab,
            code.co_freevars,
            code.co_cellvars,
        )

    # Generate the new wrapper function and its signature
    __globals__ = getattr(wrapped, "__globals__", builtins.__dict__)
    import functools

    wrapper = types.FunctionType(code, __globals__, wrapped.__name__)

    wrapper.__doc__ = wrapped.__doc__
    wrapper.__qualname__ = wrapped.__qualname__
    wrapper.__defaults__ = tuple((v for k, v in defaults[:positional]))
    wrapper.__kwdefaults__ = {k: v for k, v in defaults[positional:]}
    wrapper.__annotations__ = annotations
    wrapper.__dynamic__ = True

    if not reuse:
        setattr(cls, name + "_wrapped", wrapped)
    setattr(cls, name, wrapper)

    wrapper.__doc__ = wrapper.__origdoc__ = orig_doc


if not hasattr(sys.exc_info, "lb_wrapped"):
    # monkeypatch sys.exc_info if it needs
    sys.exc_info, exc_info = _filtered_exc_info(sys.exc_info), sys.exc_info


def sleep(seconds, tick=1.0):
    """Drop-in replacement for time.sleep that raises ConcurrentException
    if another thread requests that all threads stop.
    """
    t0 = time.time()
    global stop_request_event
    remaining = 0

    while True:
        # Raise ConcurrentException if the stop_request_event is set
        if stop_request_event.wait(min(remaining, tick)):
            raise ThreadEndedByMaster

        remaining = seconds - (time.time() - t0)

        # Return normally if the sleep finishes as requested
        if remaining <= 0:
            return


def check_hanging_thread():
    """Raise ThreadEndedByMaster if the process has requested this
    thread to end.
    """
    sleep(0.0)


@hide_in_traceback
def retry(
    exception_or_exceptions, tries=4, delay=0, backoff=0, exception_func=lambda: None
):
    """This decorator causes the function call to repeat, suppressing specified exception(s), until a
    maximum number of retries has been attempted.
    - If the function raises the exception the specified number of times, the underlying exception is raised.
    - Otherwise, return the result of the function call.

    :example:
    The following retries the telnet connection 5 times on ConnectionRefusedError::

        import telnetlib

        # Retry a telnet connection 5 times if the telnet library raises ConnectionRefusedError
        @retry(ConnectionRefusedError, tries=5)
        def open(host, port):
            t = telnetlib.Telnet()
            t.open(host,port,5)
            return t


    Inspired by https://github.com/saltycrane/retry-decorator which is released
    under the BSD license.

    Arguments:
        exception_or_exceptions: Exception (sub)class (or tuple of exception classes) to watch for
        tries: number of times to try before giving up
    :type tries: int
        delay: initial delay between retries in seconds
    :type delay: float
        backoff: backoff to multiply to the delay for each retry
    :type backoff: float
        exception_func: function to call on exception before the next retry
    :type exception_func: callable
    """

    def decorator(f):
        @wraps(f)
        @hide_in_traceback
        def do_retry(*args, **kwargs):
            notified = False
            active_delay = delay
            for retry in range(tries):
                try:
                    ret = f(*args, **kwargs)
                except exception_or_exceptions as e:
                    if not notified:
                        etype = type(e).__qualname__
                        msg = (
                            f"caught '{etype}' on first call to '{f.__name__}' - repeating the call "
                            f"{tries-1} more times or until no exception is raised"
                        )

                        callable_logger(f).info(msg)

                        notified = True
                    ex = e
                    exception_func()
                    sleep(active_delay)
                    active_delay = active_delay * backoff
                else:
                    break
            else:
                raise ex

            return ret

        return do_retry

    return decorator


@hide_in_traceback
def until_timeout(
    exception_or_exceptions, timeout, delay=0, backoff=0, exception_func=lambda: None
):
    """This decorator causes the function call to repeat, suppressing specified exception(s), until the
    specified timeout period has expired.
    - If the timeout expires, the underlying exception is raised.
    - Otherwise, return the result of the function call.

    Inspired by https://github.com/saltycrane/retry-decorator which is released
    under the BSD license.


    :example:
    The following retries the telnet connection for 5 seconds on ConnectionRefusedError::

        import telnetlib

        @until_timeout(ConnectionRefusedError, 5)
        def open(host, port):
            t = telnetlib.Telnet()
            t.open(host,port,5)
            return t

    Arguments:
        exception_or_exceptions: Exception (sub)class (or tuple of exception classes) to watch for
        timeout: time in seconds to continue calling the decorated function while suppressing exception_or_exceptions
    :type timeout: float
        delay: initial delay between retries in seconds
    :type delay: float
        backoff: backoff to multiply to the delay for each retry
    :type backoff: float
        exception_func: function to call on exception before the next retry
    :type exception_func: callable
    """

    def decorator(f):
        @wraps(f)
        @hide_in_traceback
        def do_retry(*args, **kwargs):
            notified = False
            active_delay = delay
            t0 = time.time()
            while time.time() - t0 < timeout:
                try:
                    ret = f(*args, **kwargs)
                except exception_or_exceptions as e:
                    progress = time.time() - t0

                    if not notified and timeout - progress > 0:
                        etype = type(e).__qualname__
                        msg = (
                            f"caught '{etype}' in first call to '{f.__name__}' - repeating calls for "
                            f"another {timeout-progress:0.3f}s, or until no exception is raised"
                        )

                        callable_logger(f).info(msg)

                        notified = True

                    ex = e
                    exception_func()
                    sleep(active_delay)
                    active_delay = active_delay * backoff
                else:
                    break
            else:
                raise ex

            return ret

        return do_retry

    return decorator


def timeout_iter(duration):
    """sets a timer for `duration` seconds, yields time elapsed as long as timeout has not been reached"""

    t0 = time.perf_counter()
    elapsed = 0

    while elapsed < duration:
        yield elapsed
        elapsed = time.perf_counter() - t0


def kill_by_name(*names):
    """Kill one or more running processes by the name(s) of matching binaries.

    Arguments:
        names: list of names of processes to kill
    :type names: str

    :example:
    >>> # Kill any binaries called 'notepad.exe' or 'notepad2.exe'
    >>> kill_by_name('notepad.exe', 'notepad2.exe')

    :Notes:
    Looks for a case-insensitive match against the Process.name() in the
    psutil library. Though psutil is cross-platform, the naming convention
    returned by name() is platform-dependent. In windows, for example, name()
    usually ends in '.exe'.
    """
    for pid in psutil.pids():
        try:
            proc = psutil.Process(pid)
            for target in names:
                if proc.name().lower() == target.lower():
                    logger.info(f"killing process {proc.name()}")
                    proc.kill()
        except psutil.NoSuchProcess:
            continue


def hash_caller(call_depth=1):
    """Use introspection to return an SHA224 hex digest of the caller, which
    is almost certainly unique to the combination of the caller source code
    and the arguments passed it.
    """
    import inspect
    import pickle

    thisframe = inspect.currentframe()
    frame = inspect.getouterframes(thisframe)[call_depth]
    arginfo = inspect.getargvalues(frame.frame)

    # get the function object for a simple function
    if frame.function in frame.frame.f_globals:
        func = frame.frame.f_globals[frame.function]
        argnames = arginfo.args

    # get the function object for a method in a class
    elif len(arginfo.args) > 0:  # arginfo.args[0] == 'self':
        name = arginfo.args[0]
        if name not in frame.frame.f_locals:
            raise ValueError("failed to find function object by introspection")
        func = getattr(frame.frame.f_locals[name], frame.function)
        argnames = arginfo.args[1:]

    # there weren't any arguments
    else:
        argnames = []

    args = [arginfo.locals[k] for k in argnames]

    s = inspect.getsource(func) + str(pickle.dumps(args))
    return hashlib.sha224(s.encode("ascii")).hexdigest()


@contextmanager
def stopwatch(desc: str = "", threshold: float = 0):
    """Time a block of code using a with statement like this:

    >>> with stopwatch('sleep statement'):
    >>>     time.sleep(2)
    sleep statement time elapsed 1.999s.

    Arguments:
        desc: text for display that describes the event being timed
        threshold: only show timing if at least this much time (in s) elapsed
    :
    Returns:
        context manager
    """
    t0 = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - t0
        if elapsed >= threshold:
            msg = str(desc) + " " if len(desc) else ""
            msg += f"{elapsed:0.3f} s elapsed"

            exc_info = sys.exc_info()
            if exc_info != (None, None, None):
                msg += f" before exception {exc_info[1]}"

            logger.info(msg.lstrip())


class Call(object):
    """Wrap a function to apply arguments for threaded calls to `concurrently`.
    This can be passed in directly by a user in order to provide arguments;
    otherwise, it will automatically be wrapped inside `concurrently` to
    keep track of some call metadata during execution.
    """

    def __init__(self, func, *args, **kws):
        if not callable(func):
            raise ValueError("`func` argument is not callable")
        self.func = func
        self.name = self.func.__name__
        self.args = args
        self.kws = kws
        self.queue = None

    def __repr__(self):
        args = ",".join(
            [repr(v) for v in self.args]
            + [(k + "=" + repr(v)) for k, v in self.kws.items()]
        )
        qualname = self.func.__module__ + "." + self.func.__qualname__
        return f"Call({qualname},{args})"

    @hide_in_traceback
    def __call__(self):
        try:
            self.result = self.func(*self.args, **self.kws)
        except BaseException:
            self.result = None
            self.traceback = sys.exc_info()
        else:
            self.traceback = None

        if self.queue is not None:
            self.queue.put(self)
        else:
            return self.result

    def set_queue(self, queue):
        """Set the queue object used to communicate between threads"""
        self.queue = queue

    @classmethod
    def wrap_list_to_dict(cls, name_func_pairs):
        """adjusts naming and wraps callables with Call"""
        ret = {}
        # First, generate the list of callables
        for name, func in name_func_pairs:
            try:
                if name is None:
                    if hasattr(func, "name"):
                        name = func.name
                    elif hasattr(func, "__name__"):
                        name = func.__name__
                    else:
                        raise TypeError(f"could not find name of {func}")

                if not isinstance(func, cls):
                    func = cls(func)

                func.name = name

                if name in ret:
                    msg = (
                        f"another callable is already named {repr(name)} - "
                        "pass as a keyword argument to specify a different name"
                    )
                    raise KeyError(msg)

                ret[name] = func
            except:
                raise

        return ret


class MultipleContexts:
    """Handle opening multiple contexts in a single `with` block. This is
    a threadsafe implementation that accepts a handler function that may
    implement any desired any desired type of concurrency in entering
    each context.

    The handler is responsible for sequencing the calls that enter each
    context. In the event of an exception, `MultipleContexts` calls
    the __exit__ condition of each context that has already
    been entered.

    In the current implementation, __exit__ calls are made sequentially
    (not through call_handler), in the reversed order that each context
    __enter__ was called.
    """

    def __init__(
        self, call_handler: Callable[[dict, list, dict], dict], params: dict, objs: list
    ):
        """
            call_handler: one of `sequentially_call` or `concurrently_call`
            params: a dictionary of operating parameters (see `concurrently`)
            objs: a list of contexts to be entered and dict-like objects to return

        Returns:

            context object for use in a `with` statement

        """

        # enter = self.enter
        # def wrapped_enter(name, context):
        #     return enter(name, context)
        # wrapped_enter.__name__ = 'MultipleContexts_enter_' + hex(id(self)+id(call_handler))

        def name(o):
            return

        self.abort = False
        self._entered = {}
        self.__name__ = "__enter__"

        # make up names for the __enter__ objects
        self.objs = [(f"enter_{type(o).__name__}_{hex(id(o))}", o) for _, o in objs]

        self.params = params
        self.call_handler = call_handler
        self.exc = {}

    @hide_in_traceback
    def enter(self, name, context):
        """
        enter!
        """
        if not self.abort:
            # proceed only if there have been no exceptions
            try:
                context.__enter__()  # start of a context entry thread
            except:
                self.abort = True
                self.exc[name] = sys.exc_info()
                raise
            else:
                self._entered[name] = context

    @hide_in_traceback
    def __enter__(self):
        calls = [(name, Call(self.enter, name, obj)) for name, obj in self.objs]

        try:
            with stopwatch(f"entry into context for {self.params['name']}", 0.5):
                self.call_handler(self.params, calls)
        except BaseException as e:
            try:
                self.__exit__(None, None, None)  # exit any open contexts before raise
            finally:
                raise e

    @hide_in_traceback
    def __exit__(self, *exc):
        with stopwatch(f"{self.params['name']} - context exit", 0.5):
            for name in tuple(self._entered.keys())[::-1]:
                context = self._entered[name]

                if name in self.exc:
                    continue

                try:
                    context.__exit__(None, None, None)
                except:
                    exc = sys.exc_info()
                    traceback.print_exc()

                    # don't overwrite the original exception, if there was one
                    self.exc.setdefault(name, exc)

            contexts = dict(self.objs)
            for name, exc in self.exc.items():
                if name in contexts and name not in self._entered:
                    try:
                        contexts[name].__exit__(None, None, None)
                    except BaseException as e:
                        if e is not self.exc[name][1]:
                            msg = (
                                f"{name}.__exit__ raised {e} in cleanup attempt after another "
                                f"exception in {name}.__enter__"
                            )

                            log_obj = callable_logger(contexts[name].__exit__)

                            log_obj.warning(msg)

        if len(self.exc) == 1:
            exc_info = list(self.exc.values())[0]
            raise exc_info[1]
        elif len(self.exc) > 1:
            ex = ConcurrentException(
                f"exceptions raised in {len(self.exc)} contexts are printed inline"
            )
            ex.thread_exceptions = self.exc
            raise ex
        if exc != (None, None, None):
            # sys.exc_info() may have been
            # changed by one of the exit methods
            # so provide explicit exception info
            for h in logger.logger.handlers:
                h.flush()

            raise exc[1]


RUNNERS = {
    (False, False): None,
    (False, True): "context",
    (True, False): "callable",
    (True, True): "both",
}

DIR_DICT = set(dir(dict))


def isdictducktype(cls):
    return set(dir(cls)).issuperset(DIR_DICT)


@hide_in_traceback
def enter_or_call(flexible_caller, objs, kws):
    """Extract value traits from the keyword arguments flags, decide whether
    `objs` and `kws` should be treated as context managers or callables,
    and then either enter the contexts or call the callables.
    """

    objs = list(objs)

    # Treat keyword arguments passed as callables should be left as callables;
    # otherwise, override the parameter
    params = dict(
        catch=False, nones=False, traceback_delay=False, flatten=True, name=None
    )

    def merge_inputs(dicts: list, candidates: list):
        """Merge nested returns and check for return data key conflicts in
        the callable
        """
        ret = {}
        for name, d in dicts:
            common = set(ret.keys()).difference(d.keys())
            if len(common) > 0:
                which = ", ".join(common)
                msg = f"attempting to merge results and dict arguments, but the key names ({which}) conflict in nested calls"
                raise KeyError(msg)
            ret.update(d)

        conflicts = set(ret.keys()).intersection([n for (n, obj) in candidates])
        if len(conflicts) > 0:
            raise KeyError("keys of conflict in nested return dictionary keys with ")

        return ret

    def merge_results(inputs, result):
        for k, v in dict(result).items():
            if isdictducktype(v.__class__):
                conflicts = set(v.keys()).intersection(start_keys)
                if len(conflicts) > 0:
                    conflicts = ",".join(conflicts)
                    raise KeyError(
                        f"conflicts in keys ({conflicts}) when merging return dictionaries"
                    )
                inputs.update(result.pop(k))

    # Pull parameters from the passed keywords
    for name in params.keys():
        if name in kws and not callable(kws[name]):
            params[name] = kws.pop(name)

    if params["name"] is None:
        # come up with a gobbledigook name that is at least unique
        frame = inspect.currentframe().f_back.f_back
        params[
            "name"
        ] = f"<{frame.f_code.co_filename}:{frame.f_code.co_firstlineno} call 0x{hashlib.md5().hexdigest()}>"

    # Combine the position and keyword arguments, and assign labels
    allobjs = list(objs) + list(kws.values())
    names = (len(objs) * [None]) + list(kws.keys())

    candidates = list(zip(names, allobjs))
    del allobjs, names

    dicts = []

    # Make sure candidates are either (1) all context managers
    # or (2) all callables. Decide what type of operation to proceed with.
    runner = None
    for i, (k, obj) in enumerate(candidates):

        # pass through dictionary objects from nested calls
        if isdictducktype(obj.__class__):
            dicts.append(candidates.pop(i))
            continue

        thisone = RUNNERS[
            (
                callable(obj) and not isinstance(obj, _GeneratorContextManager)
            ),  # Is it callable?
            (
                hasattr(obj, "__enter__") or isinstance(obj, _GeneratorContextManager)
            ),  # Is it a context manager?
        ]

        if thisone is None:
            msg = f"each argument must be a callable and/or a context manager, "

            if k is None:
                msg += f"but given {repr(obj)}"
            else:
                msg += f"but given {k}={repr(obj)}"

            raise TypeError(msg)
        elif runner in (None, "both"):
            runner = thisone
        else:
            if thisone not in (runner, "both"):
                raise TypeError(
                    f"cannot run a mixture of context managers and callables"
                )

    # Enforce uniqueness in the (callable or context manager) object
    candidate_objs = [c[1] for c in candidates]
    if len(set(candidate_objs)) != len(candidate_objs):
        raise ValueError("each callable and context manager must be unique")

    if runner is None:
        return {}
    elif runner == "both":
        raise TypeError(
            "all objects supported both calling and context management - not sure which to run"
        )
    elif runner == "context":
        if len(dicts) > 0:
            raise ValueError(
                f"unexpected return value dictionary argument for context management {dicts}"
            )
        return MultipleContexts(flexible_caller, params, candidates)
    else:
        ret = merge_inputs(dicts, candidates)
        result = flexible_caller(params, candidates)

        start_keys = set(ret.keys()).union(result.keys())
        if params["flatten"]:
            merge_results(ret, result)
        ret.update(result)
        return ret


@hide_in_traceback
def concurrently_call(params: dict, name_func_pairs: list) -> dict:
    global concurrency_count

    def traceback_skip(exc_tuple, count):
        """Skip the first `count` traceback entries in
        an exception.
        """
        tb = exc_tuple[2]
        for i in range(count):
            if tb is not None and tb.tb_next is not None:
                tb = tb.tb_next
        return exc_tuple[:2] + (tb,)

    def check_thread_support(func_in):
        """Setup threading (concurrent execution only), including
        checks for whether a Device instance indicates it supports
        concurrent execution or not.
        """
        func = func_in.func if isinstance(func_in, Call) else func_in
        if hasattr(func, "__self__") and not getattr(
            func.__self__, "concurrency", True
        ):
            # is this a Device that does not support concurrency?
            raise ConcurrentException(f"{func.__self__} does not support concurrency")
        return func_in

    stop_request_event.clear()

    results = {}

    catch = params["catch"]
    traceback_delay = params["traceback_delay"]

    # Setup calls then funcs
    # Set up mappings between wrappers, threads, and the function to call
    wrappers = Call.wrap_list_to_dict(name_func_pairs)
    threads = {name: Thread(target=w, name=name) for name, w in wrappers.items()}

    # Start threads with calls to each function
    finished = Queue()
    for name, thread in list(threads.items()):
        wrappers[name].set_queue(finished)
        thread.start()
        concurrency_count += 1

    # As each thread ends, collect the return value and any exceptions
    tracebacks = []
    parent_exception = None

    t0 = time.perf_counter()

    while len(threads) > 0:
        try:
            called = finished.get(timeout=0.25)
        except Empty:
            if time.perf_counter() - t0 > 60 * 15:
                names = ",".join(list(threads.keys()))
                logger.debug(f"{names} threads are still running")
                t0 = time.perf_counter()
            continue
        except BaseException as e:
            parent_exception = e
            stop_request_event.set()
            called = None

        if called is None:
            continue

        # Below only happens when called is not none
        if parent_exception is not None:
            names = ", ".join(list(threads.keys()))
            logger.error(
                f"raising {parent_exception.__class__.__name__} in main thread after child threads {names} return"
            )

        # if there was an exception that wasn't us ending the thread,
        # show messages
        if called.traceback is not None:

            tb = traceback_skip(called.traceback, 1)

            if called.traceback[0] is not ThreadEndedByMaster:
                #                exception_count += 1
                tracebacks.append(tb)
                last_exception = called.traceback[1]

            if not traceback_delay:
                try:
                    traceback.print_exception(*tb)
                except BaseException as e:
                    sys.stderr.write(
                        "\nthread exception, but failed to print exception"
                    )
                    sys.stderr.write(str(e))
                    sys.stderr.write("\n")
        else:
            if params["nones"] or called.result is not None:
                results[called.name] = called.result

        # Remove this thread from the dictionary of running threads
        del threads[called.name]
        concurrency_count -= 1

    # Clear the stop request, if there are no other threads that
    # still need to exit
    if concurrency_count == 0 and stop_request_event.is_set():
        stop_request_event.clear()

    # Raise exceptions as necessary
    if parent_exception is not None:
        for h in logger.logger.handlers:
            h.flush()

        for tb in tracebacks:
            try:
                traceback.print_exception(*tb)
            except BaseException:
                sys.stderr.write("\nthread error (fixme to print message)")
                sys.stderr.write("\n")

        raise parent_exception

    elif len(tracebacks) > 0 and not catch:
        for h in logger.logger.handlers:
            h.flush()
        if len(tracebacks) == 1:
            raise last_exception
        else:
            for tb in tracebacks:
                try:
                    traceback.print_exception(*tb)
                except BaseException:
                    sys.stderr.write("\nthread error (fixme to print message)")
                    sys.stderr.write("\n")

            ex = ConcurrentException(f"{len(tracebacks)} call(s) raised exceptions")
            ex.thread_exceptions = tracebacks
            raise ex

    return results


@hide_in_traceback
def concurrently(*objs, **kws):
    r"""If `*objs` are callable (like functions), call each of
     `*objs` in concurrent threads. If `*objs` are context
     managers (such as Device instances to be connected),
     enter each context in concurrent threads.

    Multiple references to the same function in `objs` only result in one call. The `catch` and `nones`
    arguments may be callables, in which case they are executed (and each flag value is treated as defaults).

    Arguments:
        objs:  each argument may be a callable (function or class that defines a __call__ method), or context manager (such as a Device instance)
        catch:  if `False` (the default), a `ConcurrentException` is raised if any of `funcs` raise an exception; otherwise, any remaining successful calls are returned as normal
        nones: if not callable and evalues as True, includes entries for calls that return None (default is False)
        flatten: if `True`, results of callables that returns a dictionary are merged into the return dictionary with update (instead of passed through as dictionaries)
        traceback_delay: if `False`, immediately show traceback information on a thread exception; if `True` (the default), wait until all threads finish
    Returns:
        the values returned by each call
    :rtype: dictionary keyed by function name

    Here are some examples:

    :Example: Call each function `myfunc1` and `myfunc2`, each with no arguments:

    >>> def do_something_1 ():
    >>>     time.sleep(0.5)
    >>>     return 1
    >>> def do_something_2 ():
    >>>     time.sleep(1)
    >>>     return 2
    >>> rets = concurrent(myfunc1, myfunc2)
    >>> rets[do_something_1]

    :Example: To pass arguments, use the Call wrapper

    >>> def do_something_3 (a,b,c):
    >>>     time.sleep(2)
    >>>     return a,b,c
    >>> rets = concurrent(myfunc1, Call(myfunc3,a,b,c=c))
    >>> rets[do_something_3]
    a, b, c

    **Caveats**

    - Because the calls are in different threads, not different processes,
      this should be used for IO-bound functions (not CPU-intensive functions).
    - Be careful about thread safety.

    When the callable object is a Device method, :func concurrency: checks
    the Device object state.concurrency for compatibility
    before execution. If this check returns `False`, this method
    raises a ConcurrentException.

    """

    return enter_or_call(concurrently_call, objs, kws)


@hide_in_traceback
def sequentially_call(params: dict, name_func_pairs: list) -> dict:
    """Emulate `concurrently_call`, with sequential execution. This is mostly
    only useful to guarantee compatibility with `concurrently_call`
    dictionary-style returns.
    """
    results = {}

    wrappers = Call.wrap_list_to_dict(name_func_pairs)

    # Run each callable
    for name, wrapper in wrappers.items():
        ret = wrapper()
        if ret is not None or params["nones"]:
            results[name] = ret

    return results


@hide_in_traceback
def sequentially(*objs, **kws):
    r"""If `*objs` are callable (like functions), call each of
     `*objs` in the given order. If `*objs` are context
     managers (such as Device instances to be connected),
     enter each context in the given order, and return a context manager
     suited for a `with` statement.
     This is the sequential implementation of the `concurrently` function,
     with a compatible convention of returning dictionaries.

    Multiple references to the same function in `objs` only result in one call. The `nones`
    argument may be callables in  case they are executed (and each flag value is treated as defaults).

    Arguments:
        objs:  each argument may be a callable (function, or class that defines a __call__ method), or context manager (such as a Device instance)
        kws: dictionary of further callables or context managers, with names set by the dictionary key
        nones: if True, include dictionary entries for calls that return None (default is False); left as another entry in `kws` if callable or a context manager
        flatten: if `True`, results of callables that returns a dictionary are merged into the return dictionary with update (instead of passed through as dictionaries)
    Returns:
        a dictionary keyed on the object name containing the return value of each function
    :rtype: dictionary of keyed by function

    Here are some examples:

    :Example: Call each function `myfunc1` and `myfunc2`, each with no arguments:

    >>> def do_something_1 ():
    >>>     time.sleep(0.5)
    >>>     return 1
    >>> def do_something_2 ():
    >>>     time.sleep(1)
    >>>     return 2
    >>> rets = concurrent(myfunc1, myfunc2)
    >>> rets[do_something_1]
    1

    :Example: To pass arguments, use the Call wrapper

    >>> def do_something_3 (a,b,c):
    >>>     time.sleep(2)
    >>>     return a,b,c
    >>> rets = concurrent(myfunc1, Call(myfunc3,a,b,c=c))
    >>> rets[do_something_3]
    a, b, c

    **Caveats**

    - Unlike `concurrently`, an exception in a context manager's __enter__
      means that any remaining context managers will not be entered.

    When the callable object is a Device method, :func concurrency: checks
    the Device object state.concurrency for compatibility
    before execution. If this check returns `False`, this method
    raises a ConcurrentException.
    """

    return enter_or_call(sequentially_call, objs, kws)


OP_CALL = "op"
OP_GET = "get"
OP_SET = "set"
OP_QUIT = None


class ThreadDelegate(object):
    _sandbox = None
    _obj = None
    _dir = None
    _repr = None

    def __init__(self, sandbox, obj, dir_, repr_):
        self._sandbox = sandbox
        self._obj = obj
        self._dir = dir_
        self._repr = repr_

    @hide_in_traceback
    def __call__(self, *args, **kws):
        return message(self._sandbox, OP_CALL, self._obj, None, args, kws)

    def __getattribute__(self, name):
        if name in delegate_keys:
            return object.__getattribute__(self, name)
        else:
            return message(self._sandbox, OP_GET, self._obj, name, None, None)

    def __dir__(self):
        return self._dir

    def __repr__(self):
        return f"ThreadDelegate({self._repr})"

    def __setattr__(self, name, value):
        if name in delegate_keys:
            return object.__setattr__(self, name, value)
        else:
            return message(self._sandbox, OP_SET, self._obj, name, value, None)


delegate_keys = set(ThreadDelegate.__dict__.keys()).difference(object.__dict__.keys())


@hide_in_traceback
def message(sandbox, *msg):
    req, rsp = sandbox._requestq, Queue(1)

    # Await and handle request. Exception should be raised in this
    # (main) thread
    req.put(msg + (rsp,), True)
    ret, exc = rsp.get(True)
    if exc is not None:
        raise exc

    return ret


class ThreadSandbox(object):
    """Execute all calls in the class in a separate background thread. This
    is intended to work around challenges in threading wrapped win32com APIs.

    Use it as follows:

        obj = ThreadSandbox(MyClass(myclassarg, myclasskw=myclassvalue))

    Then use `obj` as a normal MyClass instance.
    """

    __repr_root__ = "uninitialized ThreadSandbox"
    __dir_root__ = []
    __thread = None
    _requestq = None

    def __init__(self, factory, should_sandbox_func=None):
        # Start the thread and block until it's ready
        self._requestq = Queue(1)
        ready = Queue(1)
        self.__thread = Thread(
            target=self.__worker, args=(factory, ready, should_sandbox_func)
        )
        self.__thread.start()
        exc = ready.get(True)
        if exc is not None:
            raise exc

    @hide_in_traceback
    def __worker(self, factory, ready, sandbox_check_func):
        """This is the only thread allowed to access the protected object."""

        try:
            root = factory()

            def default_sandbox_check_func(obj):
                try:
                    return inspect.getmodule(obj).__name__.startswith(
                        inspect.getmodule(root).__name__
                    )
                except AttributeError:
                    return False

            if sandbox_check_func is None:
                sandbox_check_func = default_sandbox_check_func

            self.__repr_root__ = repr(root)
            self.__dir_root__ = sorted(list(set(dir(root) + list(sandbox_keys))))
            exc = None
        except Exception as e:
            exc = e
        finally:
            ready.put(exc, True)
        if exc:
            return

        # Do some sort of setup here
        while True:
            ret = None
            exc = None

            op, obj, name, args, kws, rsp = self._requestq.get(True)

            # End if that's good
            if op is OP_QUIT:
                break
            if obj is None:
                obj = root

            # Do the op
            try:
                if op is OP_GET:
                    ret = getattr(obj, name)
                elif op is OP_CALL:
                    ret = obj(*args, **kws)
                elif op is OP_SET:
                    ret = setattr(obj, name, args)

                # Make it a delegate if it needs to be protected
                if sandbox_check_func(ret):
                    ret = ThreadDelegate(self, ret, dir_=dir(ret), repr_=repr(ret))

            # Catch all exceptions
            except Exception as e:
                exc = e
                exc = e

            rsp.put((ret, exc), True)

        logger.debug("ThreadSandbox worker thread finished")

    @hide_in_traceback
    def __getattr__(self, name):
        if name in sandbox_keys:
            return object.__getattribute__(self, name)
        else:
            return message(self, OP_GET, None, name, None, None)

    @hide_in_traceback
    def __setattr__(self, name, value):
        if name in sandbox_keys:
            return object.__setattr__(self, name, value)
        else:
            return message(self, OP_SET, None, name, value, None)

    def _stop(self):
        message(self, OP_QUIT, None, None, None, None, None)

    def _kill(self):
        if isinstance(self.__thread, Thread):
            self.__thread.join(0)
        else:
            raise Exception("no thread running to kill")

    def __del__(self):
        try:
            del_ = message(self, OP_GET, None, "__del__", None, None)
        except AttributeError:
            pass
        else:
            del_()
        finally:
            try:
                self._kill()
            except BaseException:
                pass

    def __repr__(self):
        return f"ThreadSandbox({self.__repr_root__})"

    def __dir__(self):
        return self.__dir_root__


sandbox_keys = set(ThreadSandbox.__dict__.keys()).difference(object.__dict__.keys())


class ConfigStore:
    """Define dictionaries of configuration value traits
    in subclasses of this object. Each dictionary should
    be an attribute of the subclass. The all() class method
    returns a flattened dictionary consisting of all values
    of these dictionary attributes, keyed according to
    '{attr_name}_{attr_key}', where {attr_name} is the
    name of the dictionary attribute and {attr_key} is the
    nested dictionary key.
    """

    @classmethod
    def all(cls):
        """Return a dictionary of all attributes in the class"""
        ret = {}
        for k, v in cls.__dict__.items():
            if isinstance(v, dict) and not k.startswith("_"):
                ret.update([(k + "_" + k2, v2) for k2, v2 in v.items()])
        return ret

    @classmethod
    def frame(cls):
        """Return a pandas DataFrame containing all attributes
        in the class
        """
        import pandas as pd

        df = pd.DataFrame([cls.all()]).T
        df.columns.name = "Value"
        df.index.name = "Parameter"
        return df


import ast
import textwrap
import re


def accessed_attributes(method):
    """enumerate the attributes of the parent class accessed by `method`

    :method: callable that is a method or defined in a class
    Returns:
        tuple of attribute names
    """

    # really won't work unless method is a callable defined inside a class
    if not inspect.isroutine(method):
        raise ValueError(f"{method} is not a method")
    elif not inspect.ismethod(method) and "." not in method.__qualname__:
        raise ValueError(f"{method} is not defined in a class")

    # parse into a code tree
    source = inspect.getsource(method)

    # filter out lines that start with comments, which have no tokens and confuse textwrap.dedent
    source = "\n".join(re.findall("^[\ \t\r\n]*[^\#].*", source, re.MULTILINE))

    parsed = ast.parse(textwrap.dedent(source))
    if len(parsed.body) > 1:
        # this should not be possible
        raise Exception("ast parsing gave unexpected extra nodes")

    # pull out the function node and the name for the class instance
    func = parsed.body[0]
    if not isinstance(func, ast.FunctionDef):
        raise SyntaxError("this object doesn't look like a method")

    self_name = func.args.args[0].arg

    def isselfattr(node):
        return (
            isinstance(node, ast.Attribute)
            and getattr(node.value, "id", None) == self_name
        )

    return tuple({node.attr for node in ast.walk(func) if isselfattr(node)})
