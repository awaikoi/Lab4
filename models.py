import sqlite3
from datetime import datetime

from flask import current_app, g

ORDER_STATUSES = ['Нове', 'В обробці', 'Відправлено', 'Доставлено', 'Скасовано']

SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    email      TEXT NOT NULL,
    message    TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES categories(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS products (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    price         REAL NOT NULL CHECK (price >= 0),
    image         TEXT,
    image_data    BLOB,
    image_mimetype TEXT,
    discount_percent REAL NOT NULL DEFAULT 0 CHECK (discount_percent BETWEEN 0 AND 100),
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT NOT NULL,
    address     TEXT NOT NULL,
    total_price REAL NOT NULL,
    status      TEXT NOT NULL,
    date        TEXT NOT NULL,
    subtotal    REAL NOT NULL DEFAULT 0,
    discount_amount REAL NOT NULL DEFAULT 0,
    promo_code  TEXT
);

CREATE TABLE IF NOT EXISTS promocodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    discount_percent REAL NOT NULL DEFAULT 0 CHECK (discount_percent BETWEEN 0 AND 100),
    discount_amount REAL NOT NULL DEFAULT 0 CHECK (discount_amount >= 0),
    min_order REAL NOT NULL DEFAULT 0 CHECK (min_order >= 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    expires_at TEXT
);

-- Проміжна таблиця зв'язку «багато-до-багатьох» між замовленнями й товарами.
-- unit_price зберігає ціну на момент замовлення: якщо ціну товару потім
-- змінять, історія замовлень залишиться правильною.
CREATE TABLE IF NOT EXISTS order_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id   INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity   INTEGER NOT NULL CHECK (quantity > 0),
    unit_price REAL NOT NULL,
    FOREIGN KEY (order_id)   REFERENCES orders (id)   ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE RESTRICT
);
"""


def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


def close_db(exception=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(SCHEMA)

    # Безпечна міграція для вже наявної бази: старі URL у image залишаються.
    columns = {row['name'] for row in db.execute('PRAGMA table_info(products)')}
    if 'image_data' not in columns:
        db.execute('ALTER TABLE products ADD COLUMN image_data BLOB')
    if 'image_mimetype' not in columns:
        db.execute('ALTER TABLE products ADD COLUMN image_mimetype TEXT')
    product_columns = {row['name'] for row in db.execute('PRAGMA table_info(products)')}
    if 'discount_percent' not in product_columns:
        db.execute('ALTER TABLE products ADD COLUMN discount_percent REAL NOT NULL DEFAULT 0')
    if 'category_id' not in product_columns:
        db.execute('ALTER TABLE products ADD COLUMN category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL')

    order_columns = {row['name'] for row in db.execute('PRAGMA table_info(orders)')}
    if 'subtotal' not in order_columns:
        db.execute('ALTER TABLE orders ADD COLUMN subtotal REAL NOT NULL DEFAULT 0')
    if 'discount_amount' not in order_columns:
        db.execute('ALTER TABLE orders ADD COLUMN discount_amount REAL NOT NULL DEFAULT 0')
    if 'promo_code' not in order_columns:
        db.execute('ALTER TABLE orders ADD COLUMN promo_code TEXT')
    db.commit()



def add_feedback(name, email, message):
    db = get_db()
    with db:
        db.execute(
            'INSERT INTO feedback (name, email, message, created_at) VALUES (?, ?, ?, ?)',
            (name, email, message, now()),
        )


def get_feedback():
    return get_db().execute('SELECT * FROM feedback ORDER BY id DESC').fetchall()


def delete_feedback(feedback_id):
    db = get_db()
    with db:
        db.execute('DELETE FROM feedback WHERE id = ?', (feedback_id,))



def get_products(search='', category_id=None, min_price=None, max_price=None,
                 on_sale=False, sort='id'):
    """Пошук і фільтрація товарів, включно з вкладеними категоріями."""
    db = get_db()
    clauses = []
    params = []
    if search:
        clauses.append('p.name LIKE ?')
        params.append(f'%{search}%')
    if category_id:
        category_ids = get_category_descendant_ids(int(category_id))
        placeholders = ','.join('?' * len(category_ids))
        clauses.append(f'p.category_id IN ({placeholders})')
        params.extend(category_ids)
    if min_price is not None:
        clauses.append('p.price >= ?')
        params.append(min_price)
    if max_price is not None:
        clauses.append('p.price <= ?')
        params.append(max_price)
    if on_sale:
        clauses.append('COALESCE(p.discount_percent, 0) > 0')

    order_by = {
        'name': 'p.name COLLATE NOCASE',
        'name_desc': 'p.name COLLATE NOCASE DESC',
        'price': 'p.price',
        'price_desc': 'p.price DESC',
        'new': 'p.id DESC',
    }.get(sort, 'p.id')
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ''
    return db.execute(
        'SELECT p.*, c.name AS category_name '
        'FROM products p LEFT JOIN categories c ON c.id = p.category_id'
        f'{where} ORDER BY {order_by}',
        params,
    ).fetchall()


def get_product(product_id):
    return get_db().execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()


def get_products_by_ids(ids):
    ids = list(ids)
    if not ids:
        return []
    placeholders = ','.join('?' * len(ids))
    return get_db().execute(
        f'SELECT * FROM products WHERE id IN ({placeholders}) ORDER BY id', ids
    ).fetchall()


def add_product(name, price, image='', image_data=None, image_mimetype=None,
                discount_percent=0, category_id=None):
    db = get_db()
    with db:
        db.execute(
            'INSERT INTO products (name, price, image, image_data, image_mimetype, discount_percent, category_id) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (name, price, image, image_data, image_mimetype, discount_percent, category_id),
        )


def update_product(product_id, name, price, image='', image_data=None, image_mimetype=None,
                   discount_percent=0, category_id=None):
    db = get_db()
    with db:
        if image_data is None:
            # Якщо новий файл не вибрали, залишаємо попереднє зображення.
            db.execute(
                'UPDATE products SET name = ?, price = ?, image = ?, discount_percent = ?, category_id = ? WHERE id = ?',
                (name, price, image, discount_percent, category_id, product_id),
            )
        else:
            db.execute(
                'UPDATE products SET name = ?, price = ?, image = ?, '
                'image_data = ?, image_mimetype = ?, discount_percent = ?, category_id = ? WHERE id = ?',
                (name, price, image, image_data, image_mimetype, discount_percent, category_id, product_id),
            )


def delete_product(product_id):
    db = get_db()
    with db:
        db.execute('DELETE FROM products WHERE id = ?', (product_id,))


def get_categories():
    return get_db().execute(
        'SELECT c.*, p.name AS parent_name '
        'FROM categories c LEFT JOIN categories p ON p.id = c.parent_id '
        'ORDER BY c.name COLLATE NOCASE'
    ).fetchall()


def get_category(category_id):
    return get_db().execute('SELECT * FROM categories WHERE id = ?', (category_id,)).fetchone()


def get_category_descendant_ids(category_id):
    categories = get_categories()
    children = {}
    for category in categories:
        children.setdefault(category['parent_id'], []).append(category['id'])
    result = []
    stack = [category_id]
    while stack:
        current = stack.pop()
        if current not in result:
            result.append(current)
            stack.extend(children.get(current, []))
    return result


def get_category_tree():
    categories = get_categories()
    by_parent = {}
    for category in categories:
        by_parent.setdefault(category['parent_id'], []).append(dict(category))
    result = []

    def visit(parent_id, level):
        for category in by_parent.get(parent_id, []):
            category['level'] = level
            result.append(category)
            visit(category['id'], level + 1)

    visit(None, 0)
    return result


def add_category(name, parent_id=None):
    db = get_db()
    name = name.strip()
    if not name:
        raise ValueError('Вкажіть назву категорії.')
    if parent_id:
        parent = get_category(parent_id)
        if parent is None:
            raise ValueError('Батьківську категорію не знайдено.')
    with db:
        cur = db.execute(
            'INSERT INTO categories (name, parent_id) VALUES (?, ?)',
            (name, parent_id),
        )
        return cur.lastrowid


def update_category(category_id, name, parent_id=None):
    name = name.strip()
    if not name:
        raise ValueError('Вкажіть назву категорії.')
    if parent_id:
        if int(parent_id) == int(category_id):
            raise ValueError('Категорія не може бути власним батьком.')
        if int(parent_id) in get_category_descendant_ids(category_id):
            raise ValueError('Неможливо створити циклічне вкладення.')
    db = get_db()
    with db:
        db.execute(
            'UPDATE categories SET name = ?, parent_id = ? WHERE id = ?',
            (name, parent_id, category_id),
        )


def delete_category(category_id):
    with get_db() as db:
        db.execute('DELETE FROM categories WHERE id = ?', (category_id,))


def effective_product_price(product):
    discount = max(0, min(float(product['discount_percent'] or 0), 100))
    return round(float(product['price']) * (1 - discount / 100), 2)


def get_promocodes():
    return get_db().execute(
        'SELECT * FROM promocodes ORDER BY id DESC'
    ).fetchall()


def get_promocode(code):
    return get_db().execute(
        'SELECT * FROM promocodes WHERE upper(code) = upper(?)',
        (code.strip(),),
    ).fetchone()


def add_promocode(code, discount_percent=0, discount_amount=0, min_order=0, active=True, expires_at=None):
    code = code.strip().upper()
    if not code:
        raise ValueError('Вкажіть промокод.')
    if discount_percent < 0 or discount_percent > 100:
        raise ValueError('Відсоткова знижка має бути від 0 до 100.')
    if discount_amount < 0:
        raise ValueError('Фіксована знижка не може бути відʼємною.')
    db = get_db()
    with db:
        cur = db.execute(
            'INSERT INTO promocodes (code, discount_percent, discount_amount, min_order, active, expires_at) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (code, discount_percent, discount_amount, min_order, 1 if active else 0, expires_at),
        )
        return cur.lastrowid


def update_promocode(promo_id, code, discount_percent=0, discount_amount=0, min_order=0, active=True, expires_at=None):
    code = code.strip().upper()
    if not code:
        raise ValueError('Вкажіть промокод.')
    db = get_db()
    with db:
        db.execute(
            'UPDATE promocodes SET code=?, discount_percent=?, discount_amount=?, min_order=?, active=?, expires_at=? WHERE id=?',
            (code, discount_percent, discount_amount, min_order, 1 if active else 0, expires_at, promo_id),
        )


def delete_promocode(promo_id):
    with get_db() as db:
        db.execute('DELETE FROM promocodes WHERE id = ?', (promo_id,))


def validate_promocode(code, subtotal):
    promo = get_promocode(code)
    if promo is None:
        return None, 'Промокод не знайдено.'
    if not promo['active']:
        return None, 'Цей промокод неактивний.'
    if promo['expires_at'] and promo['expires_at'] < now()[:10]:
        return None, 'Термін дії промокоду завершено.'
    if subtotal < promo['min_order']:
        return None, f'Мінімальна сума замовлення для цього промокоду: {promo["min_order"]:.2f} грн.'
    return promo, None


def calculate_promocode_discount(promo, subtotal):
    percent_discount = round(subtotal * float(promo['discount_percent']) / 100, 2)
    fixed_discount = float(promo['discount_amount'])
    # Найбільша оголошена знижка застосовується як єдина знижка.
    return round(min(subtotal, max(percent_discount, fixed_discount)), 2)


# Короткі псевдоніми для сумісності з іншими частинами застосунку.
get_promos = get_promocodes
get_promo = get_promocode
add_promo = add_promocode
delete_promo = delete_promocode


def create_order(email, address, cart, promo_code=None):
    products = get_products_by_ids(cart.keys())
    if not products:
        raise ValueError('Кошик порожній')

    subtotal = round(sum(effective_product_price(p) * cart[p['id']] for p in products), 2)
    promo = None
    promo_discount = 0
    if promo_code:
        promo, error = validate_promocode(promo_code, subtotal)
        if error:
            raise ValueError(error)
        promo_discount = calculate_promocode_discount(promo, subtotal)
    total = round(max(0, subtotal - promo_discount), 2)
    db = get_db()
    with db:
        cur = db.execute(
            'INSERT INTO orders (email, address, total_price, status, date, subtotal, discount_amount, promo_code) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (email, address, total, ORDER_STATUSES[0], now(), subtotal, promo_discount, promo['code'] if promo else None),
        )
        order_id = cur.lastrowid
        db.executemany(
            'INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)',
            [(order_id, p['id'], cart[p['id']], effective_product_price(p)) for p in products],
        )
    return order_id


def get_orders():
    return get_db().execute('SELECT * FROM orders ORDER BY id DESC').fetchall()


def get_order_details(order_id):
    db = get_db()
    order = db.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    items = db.execute(
        'SELECT p.name, oi.quantity, oi.unit_price '
        'FROM order_items oi JOIN products p ON oi.product_id = p.id '
        'WHERE oi.order_id = ? ORDER BY oi.id',
        (order_id,),
    ).fetchall()
    return order, items


def update_order_status(order_id, status):
    if status not in ORDER_STATUSES:
        raise ValueError(f'Невідомий статус: {status}')
    db = get_db()
    with db:
        db.execute('UPDATE orders SET status = ? WHERE id = ?', (status, order_id))


def delete_order(order_id):
    db = get_db()
    with db:
        db.execute('DELETE FROM orders WHERE id = ?', (order_id,))

