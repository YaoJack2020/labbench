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

import datetime
import io
import json
import logging
import os
import socket
import sys
import time

from . import _device as core
from . import datareturn
from . import property as property_
from . import util, value

__all__ = ["Host", "Email"]


class LogStreamBuffer:
    def __init__(self):
        self._value = ""

    def write(self, msg):
        self._value = self._value + msg
        return len(msg)

    def read(self):
        ret, self._value = self._value, ""
        return ret

    def flush(self):
        pass


class LogStderr(core.Device):
    """This "Device" logs a copy of messages on sys.stderr while connected."""

    log = ""

    def open(self):
        self._stderr, self._buf, sys.stderr = sys.stderr, io.StringIO(), self

    def close(self):
        if self.isopen:
            sys.stderr = self._stderr
            self.log = self._buf.getvalue()
            self._buf.close()

    def write(self, what):
        self._stderr.write(what)
        self._buf.write(what)

    def flush(self):
        try:
            self._buf.flush()
            self.log += self._buf.getvalue()
        except ValueError:
            pass


class Email(core.Device):
    """Sends a notification message on disconnection. If an exception
    was thrown, this is a failure subject line with traceback information
    in the main body. Otherwise, the message is a success message in the
    subject line. Stderr is also sent.
    """

    resource = value.NetworkAddress(default="smtp.nist.gov", help="smtp server to use")

    port = value.int(default=25, min=1, help="TCP/IP port")

    sender = value.str(default="myemail@nist.gov", help="email address of the sender")

    recipients = value.list(
        default=["myemail@nist.gov"], help="list of email addresses of recipients"
    )

    success_message = value.str(
        default="Test finished normally",
        allow_none=True,
        help="subject line for test success emails (None to suppress the emails)",
    )

    failure_message = value.str(
        default="Exception ended test early",
        allow_none=True,
        help="subject line for test failure emails (None to suppress the emails)",
    )

    def _send(self, subject, body):
        sys.stderr.flush()
        self.backend.flush()
        import smtplib
        from email.mime.text import MIMEText

        msg = MIMEText(body, "html")
        msg["From"] = self.sender
        msg["Subject"] = subject
        msg["To"] = ", ".join(self.recipients)
        self.server = smtplib.SMTP(self.resource, self.port)

        try:
            self.server.sendmail(self.sender, self.recipients, msg.as_string())
        finally:
            self.server.quit()

    def open(self):
        self.backend = LogStderr()
        self.backend.open()

    def close(self):
        if self.isopen:
            self.backend.close()
            util.sleep(1)
            self.send_summary()

    def send_summary(self):
        """Send the email containing the final property trait of the test."""
        exc = sys.exc_info()

        if exc[0] is KeyboardInterrupt:
            return

        if exc != (None, None, None):
            from traceback import format_exc

            if self.failure_message is None:
                return
            subject = self.failure_message
            message = (
                "<b>Exception</b>\n"
                + '<font face="Courier New, Courier, monospace">'
                + format_exc()
                + "</font>"
            )
        else:
            if self.success_message is None:
                return
            subject = self.success_message
            message = ""

        if len(self.backend.log) > 0:
            message = (
                message
                + "\n\n<b>Standard error</b>\n"
                + '<font face="Courier New, Courier, monospace">'
                + self.backend.log
                + "</font>"
            )

        self._send(subject, message.replace("\n", "<br>"))

        return subject, message


class JSONFormatter(logging.Formatter):
    _last = []

    def __init__(self, *args, **kws):
        super().__init__(*args, **kws)
        self.t0 = time.time()

    @staticmethod
    def json_serialize_dates(obj):
        """JSON serializer for objects not serializable by default json code"""

        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj).__qualname__} not serializable")

    def format(self, rec):
        """Return a YAML string for each logger record"""

        # if isinstance(rec, core.Device):
        #     log_prefix = rec._owned_name.replace(".", ",")
        # else:
        #     log_prefix = ''

        # object = getattr(rec, 'object', None)

        msg = dict(
            message=rec.msg,
            time=datetime.datetime.fromtimestamp(rec.created),
            elapsed_seconds=rec.created - self.t0,
            level=rec.levelname,
            object=getattr(rec, "object", None),
            object_log_name=getattr(rec, "owned_name", None),
            source_file=rec.pathname,
            source_line=rec.lineno,
            process=rec.process,
            thread=rec.threadName,
        )

        if rec.threadName != "MainThread":
            msg["thread"] = rec.threadName

        etype, einst, exc_tb = sys.exc_info()
        if etype is not None:
            from traceback import format_exception_only, format_tb

            msg["exception"] = format_exception_only(etype, einst)[0].rstrip()
            msg["traceback"] = "".join(format_tb(exc_tb)).splitlines()

        self._last.append((rec, msg))

        return json.dumps(msg, indent=True, default=self.json_serialize_dates) + ","


class Host(core.Device):
    # Settings
    git_commit_in = value.str(
        default=None,
        allow_none=True,
        help="git commit on open() if run inside a git repo with this branch name",
    )

    time_format = "%Y-%m-%d %H:%M:%S"

    def open(self):
        """The host setup method tries to commit current changes to the tree"""
        log_formatter = JSONFormatter()
        stream = LogStreamBuffer()
        sh = logging.StreamHandler(stream)
        sh.setFormatter(log_formatter)
        sh.setLevel(logging.DEBUG)

        # Add to the labbench logger handler
        logger = logging.getLogger("labbench")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(sh)

        # git repository information
        try:
            repo = git.Repo(".", search_parent_directories=True)
            self._logger.debug("running in git repository")
            if self.git_commit_in is not None and repo.active_branch == self.git_commit_in:
                repo.index.commit("start of measurement")
                self._logger.debug("git commit finished")
        except git.NoSuchPathError:
            repo = None
            self._logger.info(f"not running in a git repository")

        self.backend = {
            "logger": logger,
            "log_stream": stream,
            "log_handler": sh,
            "log_formatter": log_formatter,
            "repo": repo,
        }

        # Preload the git repo parameters
        for name in self._traits:
            if name.startswith("git"):
                getattr(self, name)

    @classmethod
    def __imports__(self):
        global git, pip
        import git
        import pip

    def close(self):
        try:
            self.backend["logger"].removeHandler(self.backend["log_handler"])
        except (AttributeError, TypeError):
            pass
        try:
            self.backend["log_stream"].close()
        except (AttributeError, TypeError):
            pass

    def metadata(self):
        """Generate the metadata associated with the host and python distribution"""
        ret = super().metadata()
        ret["python_modules"] = self.__python_module_versions()
        return ret

    def __python_module_versions(self):
        """Enumerate the versions of installed python modules"""
        import pandas as pd

        versions = dict(
            [str(d).lower().split(" ") for d in pip.get_installed_distributions()]
        )
        running = dict(
            sorted(
                [(k, versions[k.lower()]) for k in sys.modules.keys() if k in versions]
            )
        )
        return pd.Series(running).sort_index()

    @property_.str()
    def time(self):
        """Get a timestamp of the current time"""
        now = datetime.datetime.now()
        return f"{now.strftime(self.time_format)}.{now.microsecond}"

    @property_.list()
    def log(self):
        """Get the current host log contents."""
        self.backend["log_handler"].flush()
        txt = self.backend["log_stream"].read()
        if len(txt) > 1:
            self._txt = txt
            self._serialized = "[" + txt[:-2] + "]"
            self._ret = json.loads(
                self._serialized
            )  # self.backend['log_stream'].read().replace('\n', '\r\n')
            return self._ret
        else:
            return {}

    @property_.str(cache=True)
    def git_commit_id(self):
        """Try to determine the current commit hash of the current git repo"""
        try:
            commit = self.backend["repo"].commit()
            return commit.hexsha
        except git.NoSuchPathError:
            return ""

    @property_.str(cache=True)
    def git_remote_url(self):
        """Try to identify the remote URL of the repository of the current git repo"""
        try:
            return next(self.backend["repo"].remote().urls)
        except BaseException:
            return ""

    @property_.str(cache=True)
    def hostname(self):
        """Get the name of the current host"""
        return socket.gethostname()

    @property_.str(cache=True)
    def git_browse_url(self):
        """URL for browsing the current git repository"""
        return f"{self.git_remote_url}/tree/{self.git_commit_id}"

    @property_.str(cache=True)
    def git_pending_changes(self):
        if self.backend["repo"] is not None:
            diffs = self.backend["repo"].index.diff(None)
            return str(tuple((diff.b_path for diff in diffs)))[1:-1]
        else:
            return ""


if __name__ == "__main__":
    #    core.show_messages('DEBUG')
    #
    #    with Host() as pc:
    #        print(pc.time)

    with Email(recipients=["daniel.kuester@nist.gov"]) as email:
        pass
