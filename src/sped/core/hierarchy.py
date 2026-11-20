"""Lazy record hierarchy for SPED files.

The official layout manuals publish a "Nível Hierárquico" for every register.
The published number is used for detail registers; structural registers follow
the conventions also documented in those manuals: ``0000``/``9999`` are the
file root (0), block openers (``x001``), closers (``x990``) and Block 9 control
registers are level 1. (Some ICMS/IPI guides print inconsistent numbers for
these control registers; the code structure takes precedence.) No business
rule is inferred — levels only describe containment.

The tree is built *lazily*: records are pulled from the underlying iterator one
at a time.  :meth:`RecordTree.iter_entries` keeps only the current ancestry
stack, so it uses memory proportional to the tree depth, not the file size.
:meth:`RecordTree.iter_nodes` additionally links parent/child nodes for callers
that need navigation.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from sped.core.types import Layout, Record


def level_of(record: Record, layout: Layout) -> int:
    """Return the hierarchical level of ``record`` (official when available)."""
    code = record.code
    if code in {"0000", "9999"}:
        return 0
    # Block openers/closers and the file-control registers are always level 1,
    # even when a guide's prose table carries an inconsistent number.
    if code.endswith(("001", "990")) or code in {"9001", "9990"}:
        return 1
    if code == "9900":
        return 2
    definition = layout.registers.get(code)
    if definition is not None and definition.level is not None:
        return max(2, definition.level)
    return 2


@dataclass(slots=True)
class TreeNode:
    """One record in the hierarchy, with links to its parent and children."""

    record: Record
    level: int
    parent: TreeNode | None = field(default=None, repr=False)
    children: list[TreeNode] = field(default_factory=list)

    @property
    def code(self) -> str:
        return self.record.code

    @property
    def line_no(self) -> int:
        return self.record.line_no

    def descendants(self) -> Iterator[TreeNode]:
        """Yield every descendant of this node in document order."""
        for child in self.children:
            yield child
            yield from child.descendants()


@dataclass(frozen=True, slots=True)
class TreeEntry:
    """A streaming hierarchy entry without parent/child object links."""

    record: Record
    level: int
    parent: str | None
    block: str

    @property
    def code(self) -> str:
        return self.record.code

    @property
    def line_no(self) -> int:
        return self.record.line_no


class RecordTree:
    """Lazily walk records of one SPED file as a hierarchy.

    ``records`` is consumed at most once.  Pass a fresh iterator (for example a
    new :class:`~sped.core.reader.SpedReader`) for each new walk.
    """

    def __init__(self, records: Iterable[Record], layout: Layout) -> None:
        self._records = records
        self.layout = layout

    def iter_entries(self) -> Iterator[TreeEntry]:
        """Yield entries with level/parent while holding only the ancestry stack."""
        stack: list[tuple[int, str]] = []
        for record in self._records:
            level = level_of(record, self.layout)
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else None
            stack.append((level, record.code))
            yield TreeEntry(record=record, level=level, parent=parent, block=record.code[0])

    def iter_nodes(self) -> Iterator[TreeNode]:
        """Yield linked nodes, building the tree branch by branch.

        Nodes are materialised as they are reached; retaining a node keeps its
        subtree alive.  For flat, constant-memory traversal use
        :meth:`iter_entries`.
        """
        stack: list[TreeNode] = []
        for record in self._records:
            level = level_of(record, self.layout)
            while stack and stack[-1].level >= level:
                stack.pop()
            parent = stack[-1] if stack else None
            node = TreeNode(record=record, level=level, parent=parent)
            if parent is not None:
                parent.children.append(node)
            stack.append(node)
            yield node

    def __iter__(self) -> Iterator[TreeNode]:
        return self.iter_nodes()

    def by_type(self, code: str) -> Iterator[Record]:
        """Yield records of one register type in a single lazy pass."""
        return (entry.record for entry in self.iter_entries() if entry.record.code == code)

    def blocks(self) -> Iterator[str]:
        """Yield each block identifier once, in document order."""
        seen: set[str] = set()
        for entry in self.iter_entries():
            if entry.block not in seen:
                seen.add(entry.block)
                yield entry.block


def build_tree(records: Iterable[Record], layout: Layout) -> RecordTree:
    """Return a :class:`RecordTree` over ``records`` and ``layout``."""
    return RecordTree(records, layout)
