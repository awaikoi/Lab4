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

CREATE TABLE IF NOT EXISTS products (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    price         REAL NOT NULL CHECK (price >= 0),
    image         TEXT,
    image_data    BLOB,
    image_mimetype TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT NOT NULL,
    address     TEXT NOT NULL,
    total_price REAL NOT NULL,
    status      TEXT NOT NULL,
    date        TEXT NOT NULL
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



def get_products():
    return get_db().execute('SELECT * FROM products ORDER BY id').fetchall()


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


def add_product(name, price, image='', image_data=None, image_mimetype=None):
    db = get_db()
    with db:
        db.execute(
            'INSERT INTO products (name, price, image, image_data, image_mimetype) '
            'VALUES (?, ?, ?, ?, ?)',
            (name, price, image, image_data, image_mimetype),
        )


def update_product(product_id, name, price, image='', image_data=None, image_mimetype=None):
    db = get_db()
    with db:
        if image_data is None:
            # Якщо новий файл не вибрали, залишаємо попереднє зображення.
            db.execute(
                'UPDATE products SET name = ?, price = ?, image = ? WHERE id = ?',
                (name, price, image, product_id),
            )
        else:
            db.execute(
                'UPDATE products SET name = ?, price = ?, image = ?, '
                'image_data = ?, image_mimetype = ? WHERE id = ?',
                (name, price, image, image_data, image_mimetype, product_id),
            )


def delete_product(product_id):
    db = get_db()
    with db:
        db.execute('DELETE FROM products WHERE id = ?', (product_id,))



def create_order(email, address, cart):
    products = get_products_by_ids(cart.keys())
    if not products:
        raise ValueError('Кошик порожній')

    total = round(sum(p['price'] * cart[p['id']] for p in products), 2)
    db = get_db()
    with db:
        cur = db.execute(
            'INSERT INTO orders (email, address, total_price, status, date) VALUES (?, ?, ?, ?, ?)',
            (email, address, total, ORDER_STATUSES[0], now()),
        )
        order_id = cur.lastrowid
        db.executemany(
            'INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)',
            [(order_id, p['id'], cart[p['id']], p['price']) for p in products],
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

