from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ArgSpec:
    name: str
    # 'str' | 'int' | 'float' | 'bool' | 'list[str]' | 'dict[str,str]'
    # | 'column' | 'columns' | 'column_mapping' | 'value_mapping'
    type: str
    label: str = ''
    required: bool = False
    default: Any = None
    choices: list[Any] | None = None
    help_text: str = ''


@dataclass(frozen=True)
class ReaderSpec:
    name: str
    func: Callable
    extensions: tuple[str, ...]
    args: tuple[ArgSpec, ...] = field(default_factory=tuple)
    label: str = ''


@dataclass(frozen=True)
class TransformSpec:
    name: str
    func: Callable
    args: tuple[ArgSpec, ...] = field(default_factory=tuple)
    label: str = ''


READERS: dict[str, ReaderSpec] = {}
TRANSFORMS: dict[str, TransformSpec] = {}


def reader(name: str, *, extensions: tuple[str, ...], args: tuple[ArgSpec, ...] = (), label: str = ''):
    def decorator(fn: Callable):
        READERS[name] = ReaderSpec(name=name, func=fn, extensions=extensions, args=args, label=label or name)
        return fn
    return decorator


def transform(name: str, *, args: tuple[ArgSpec, ...] = (), label: str = ''):
    def decorator(fn: Callable):
        TRANSFORMS[name] = TransformSpec(name=name, func=fn, args=args, label=label or name)
        return fn
    return decorator


def get_reader(name: str) -> ReaderSpec:
    if name not in READERS:
        raise KeyError(f"Reader '{name}' is not registered")
    return READERS[name]


def get_transform(name: str) -> TransformSpec:
    if name not in TRANSFORMS:
        raise KeyError(f"Transform '{name}' is not registered")
    return TRANSFORMS[name]
