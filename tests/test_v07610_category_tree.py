from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import CategoryNode
from app.services.categories import build_category_tree, next_category_sort_order


def make_db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_category_tree_builds_nested_structure():
    db = make_db()
    root = CategoryNode(kind='ticket', name='Холодильное оборудование', sort_order=10)
    db.add(root); db.flush()
    child = CategoryNode(kind='ticket', name='Бонеты', parent_id=root.id, sort_order=10)
    db.add(child); db.flush()
    grandchild = CategoryNode(kind='ticket', name='Морозильные', parent_id=child.id, sort_order=10)
    db.add(grandchild); db.commit()

    rows = db.query(CategoryNode).order_by(CategoryNode.sort_order, CategoryNode.name).all()
    tree = build_category_tree(rows)
    assert len(tree) == 1
    assert tree[0]['row'].name == 'Холодильное оборудование'
    assert tree[0]['children'][0]['row'].name == 'Бонеты'
    assert tree[0]['children'][0]['children'][0]['row'].name == 'Морозильные'


def test_next_category_sort_order_is_automatic_per_parent():
    db = make_db()
    root = CategoryNode(kind='ticket', name='Ремонт', sort_order=10)
    db.add(root); db.flush()
    db.add_all([
        CategoryNode(kind='ticket', name='A', parent_id=root.id, sort_order=10),
        CategoryNode(kind='ticket', name='B', parent_id=root.id, sort_order=20),
    ])
    db.commit()
    assert next_category_sort_order(db, 'ticket', root.id) == 30
    assert next_category_sort_order(db, 'ticket', None) == 20
