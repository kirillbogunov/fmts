from __future__ import annotations
from dataclasses import dataclass
from sqlalchemy.orm import Session
from app.models import CategoryNode

@dataclass
class CategoryOption:
    id: int
    code: str
    name: str
    depth: int
    path: str

def category_options(db: Session, kind: str, include_inactive: bool = False) -> list[CategoryOption]:
    q = db.query(CategoryNode).filter(CategoryNode.kind == kind)
    if not include_inactive:
        q = q.filter(CategoryNode.active == True)
    rows = q.order_by(CategoryNode.sort_order, CategoryNode.name, CategoryNode.id).all()
    by_parent = {}
    for row in rows:
        by_parent.setdefault(row.parent_id, []).append(row)
    out = []
    visited = set()
    def walk(parent_id, prefix, depth):
        for row in by_parent.get(parent_id, []):
            if row.id in visited:
                continue
            visited.add(row.id)
            parts = prefix + [row.name]
            path = " / ".join(parts)
            out.append(CategoryOption(row.id, path, ("- " * depth) + row.name, depth, path))
            walk(row.id, parts, depth + 1)
    walk(None, [], 0)
    for row in rows:
        if row.id not in visited:
            out.append(CategoryOption(row.id, row.name, row.name, 0, row.name))
    return out

def category_path(db: Session, node: CategoryNode | None) -> str:
    if not node:
        return ""
    parts = []
    seen = set()
    cur = node
    while cur and cur.id not in seen:
        seen.add(cur.id)
        parts.append(cur.name)
        cur = db.get(CategoryNode, cur.parent_id) if cur.parent_id else None
    return " / ".join(reversed(parts))
