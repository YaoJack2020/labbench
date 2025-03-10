"""
.. This software was developed by employees of the National Institute of
.. Standards and Technology (NIST), an agency of the Federal Government.
.. Pursuant to title 17 United States Code Section 105, works of NIST employees
.. are not subject to copyright protection in the United States and are
.. considered to be in the public domain. Permission to freely use, copy,
.. modify, and distribute this software and its documentation without fee is
.. hereby granted, provided that this notice and disclaimer of warranty appears
.. in all copies.
..
.. THE SOFTWARE IS PROVIDED 'AS IS' WITHOUT ANY WARRANTY OF ANY KIND, EITHER
.. EXPRESSED, IMPLIED, OR STATUTORY, INCLUDING, BUT NOT LIMITED TO, ANY WARRANTY
.. THAT THE SOFTWARE WILL CONFORM TO SPECIFICATIONS, ANY IMPLIED WARRANTIES OF
.. MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND FREEDOM FROM
.. INFRINGEMENT, AND ANY WARRANTY THAT THE DOCUMENTATION WILL CONFORM TO THE
.. SOFTWARE, OR ANY WARRANTY THAT THE SOFTWARE WILL BE ERROR FREE. IN NO EVENT
.. SHALL NIST BE LIABLE FOR ANY DAMAGES, INCLUDING, BUT NOT LIMITED TO, DIRECT,
.. INDIRECT, SPECIAL OR CONSEQUENTIAL DAMAGES, ARISING OUT OF, RESULTING FROM,
.. OR IN ANY WAY CONNECTED WITH THIS SOFTWARE, WHETHER OR NOT BASED UPON
.. WARRANTY, CONTRACT, TORT, OR OTHERWISE, WHETHER OR NOT INJURY WAS SUSTAINED
.. BY PERSONS OR PROPERTY OR OTHERWISE, AND WHETHER OR NOT LOSS WAS SUSTAINED
.. FROM, OR AROSE OUT OF THE RESULTS OF, OR USE OF, THE SOFTWARE OR SERVICES
.. PROVIDED HEREUNDER. Distributions of NIST software should also include
.. copyright and licensing statements of any third-party software that are
.. legally bundled with the code in compliance with the conditions of those
.. licenses.
"""

from .util import (
    concurrently,
    sequentially,
    Call,
    stopwatch,
    retry,
    until_timeout,
    show_messages,
    sleep,
    logger,
    timeout_iter,
    _force_full_traceback,
)

_force_full_traceback(True)

from ._backends import (
    ShellBackend,
    DotNetDevice,
    LabviewSocketInterface,
    SerialDevice,
    SerialLoggingDevice,
    TelnetDevice,
    VISADevice,
    Win32ComDevice,
)
from ._data import CSVLogger, HDFLogger, SQLiteLogger, read, read_relational
from ._device import Device, list_devices, trait_info
from ._host import Email
from ._rack import (
    Rack,
    Sequence,
    import_as_rack,
    find_owned_rack_by_type,
    rack_input_table,
    rack_kwargs_skip,
    rack_kwargs_template,
)
from ._traits import observe, unobserve, Undefined
from ._serialize import load_rack, dump_rack
from ._version import __version__

from . import value
from . import property
from . import datareturn
from . import util

# scrub __module__ for cleaner repr() and doc
for _obj in dict(locals()).values():
    if getattr(_obj, "__module__", "").startswith("labbench."):
        _obj.__module__ = "labbench"
del _obj
