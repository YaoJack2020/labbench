import io
from . import _device as core, datareturn as datareturn, util as util, value as value
from ._device import Device as Device
from ._rack import Owner as Owner, Rack as Rack, Step as Step
from ._traits import Trait as Trait, VALID_TRAIT_ROLES as VALID_TRAIT_ROLES, observe as observe
from contextlib import ExitStack as ExitStack, contextmanager as contextmanager
from typing import Any, Optional
EMPTY: Any
INSPECT_SKIP_FILES: Any


class MungerBase(core.Device):

    def __init__(
        self,
        resource: str='WindowsPath',
        text_relational_min: str='int',
        force_relational: str='list',
        dirname_fmt: str='str',
        nonscalar_file_type: str='str',
        metadata_dirname: str='str'
    ):
        ...
    resource: Any = ...
    text_relational_min: Any = ...
    force_relational: Any = ...
    dirname_fmt: Any = ...
    nonscalar_file_type: Any = ...
    metadata_dirname: Any = ...

    def __call__(self, index: Any, row: Any):
        ...

    def save_metadata(self, name: Any, key_func: Any, **extra: Any):
        ...


class MungeToDirectory(MungerBase):

    def __init__(
        self,
        resource: str='WindowsPath',
        text_relational_min: str='int',
        force_relational: str='list',
        dirname_fmt: str='str',
        nonscalar_file_type: str='str',
        metadata_dirname: str='str'
    ):
        ...
    ...


class TarFileIO(io.BytesIO):
    tarfile: Any = ...
    overwrite: bool = ...
    name: Any = ...
    mode: Any = ...

    def __init__(self, open_tarfile: Any, relname: Any, mode: str=..., overwrite: bool=...) -> None:
        ...

    def __del__(self) -> None:
        ...

    def close(self) -> None:
        ...


class MungeToTar(MungerBase):

    def __init__(
        self,
        resource: str='WindowsPath',
        text_relational_min: str='int',
        force_relational: str='list',
        dirname_fmt: str='str',
        nonscalar_file_type: str='str',
        metadata_dirname: str='str'
    ):
        ...
    tarname: str = ...
    tarfile: Any = ...

    def open(self) -> None:
        ...

    def close(self) -> None:
        ...


class Aggregator(util.Ownable):
    name_map: Any = ...
    trait_rules: Any = ...
    metadata: Any = ...

    def __init__(self, persistent_state: bool=...) -> None:
        ...

    def __owner_init__(self, rack: Any) -> None:
        ...

    def enable(self) -> None:
        ...

    def disable(self) -> None:
        ...

    def get(self) -> dict:
        ...

    def key(self, device_name: Any, state_name: Any):
        ...

    def set_device_labels(self, **mapping: Any) -> None:
        ...

    def __update_names__(self, devices: Any) -> None:
        ...

    def observe(self, devices: Any, changes: bool=..., always: Any=..., never: Any=...) -> None:
        ...


class RelationalTableLogger(Owner, util.Ownable):
    index_label: str = ...
    aggregator: Any = ...
    host: Any = ...
    munge: Any = ...
    pending: Any = ...
    path: Any = ...

    def __init__(
        self,
        path: Any,
        *,
        append: bool=...,
        text_relational_min: int=...,
        force_relational: Any=...,
        dirname_fmt: str=...,
        nonscalar_file_type: str=...,
        metadata_dirname: str=...,
        tar: bool=...,
        git_commit_in: Optional[Any]=...,
        persistent_state: bool=...
    ) -> None:
        ...

    def __owner_init__(self, owner: Any) -> None:
        ...

    def observe(self, devices: Any, changes: bool=..., always: Any=..., never: Any=...) -> None:
        ...

    def set_row_preprocessor(self, func: Any):
        ...

    def new_row(self, *args: Any, **kwargs: Any) -> None:
        ...

    def write(self) -> None:
        ...

    def clear(self) -> None:
        ...

    def set_relational_file_format(self, format: Any) -> None:
        ...

    def set_path_format(self, format: Any) -> None:
        ...

    def open(self, path: Optional[Any]=...) -> None:
        ...

    def close(self) -> None:
        ...


class CSVLogger(RelationalTableLogger):
    nonscalar_file_type: str = ...
    path: Any = ...
    df: Any = ...

    def open(self) -> None:
        ...

    def close(self) -> None:
        ...


class MungeToHDF(Device):

    def __init__(self, resource: str='WindowsPath', key_fmt: str='str'):
        ...
    resource: Any = ...
    key_fmt: Any = ...
    backend: Any = ...

    def open(self) -> None:
        ...

    def close(self) -> None:
        ...

    def __call__(self, index: Any, row: Any):
        ...

    def save_metadata(self, name: Any, key_func: Any, **extra: Any):
        ...


class HDFLogger(RelationalTableLogger):
    nonscalar_file_type: str = ...
    munge: Any = ...

    def __init__(
        self,
        path: Any,
        *,
        append: bool=...,
        key_fmt: str=...,
        git_commit_in: Optional[Any]=...,
        persistent_state: bool=...
    ) -> None:
        ...
    df: Any = ...

    def open(self) -> None:
        ...

    def close(self) -> None:
        ...


class SQLiteLogger(RelationalTableLogger):
    index_label: str = ...
    master_filename: str = ...
    table_name: str = ...
    inprogress: Any = ...
    committed: Any = ...
    last_index: int = ...

    def open(self) -> None:
        ...

    def close(self) -> None:
        ...

    def key(self, name: Any, attr: Any):
        ...

def to_feather(data: Any, path: Any) -> None:
    ...

def read_sqlite(
    path: Any,
    table_name: str=...,
    columns: Optional[Any]=...,
    nrows: Optional[Any]=...,
    index_col: Any=...
):
    ...

def read(
    path_or_buf: Any,
    columns: Optional[Any]=...,
    nrows: Optional[Any]=...,
    format: str=...,
    **kws: Any
):
    ...


class MungeTarReader():
    tarnames: Any = ...
    tarfile: Any = ...

    def __init__(self, path: Any, tarname: str=...) -> None:
        ...

    def __call__(self, key: Any, *args: Any, **kws: Any):
        ...


class MungeDirectoryReader():
    path: Any = ...

    def __init__(self, path: Any) -> None:
        ...

    def __call__(self, key: Any, *args: Any, **kws: Any):
        ...


class MungeReader():

    def __new__(cls, path: Any):
        ...

def read_relational(
    path: Any,
    expand_col: Any,
    master_cols: Optional[Any]=...,
    target_cols: Optional[Any]=...,
    master_nrows: Optional[Any]=...,
    master_format: str=...,
    prepend_column_name: bool=...
):
    ...
