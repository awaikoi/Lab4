import sqlite3

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

import models

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


MAX_IMAGE_SIZE = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {
    'image/jpeg': (b'\\xff\\xd8\\xff',),
    'image/png': (b'\\x89PNG\\r\\n\\x1a\\n',),
    'image/gif': (b'GIF87a', b'GIF89a'),
    'image/webp': (b'RIFF',),  # додаткова перевірка WEBP нижче
}


def read_uploaded_image():
    """Повертає (байти, MIME, помилка). Порожній файл означає: зображення не змінювали."""
    uploaded = request.files.get('image_file')
    if uploaded is None or not uploaded.filename:
        return None, None, None

    data = uploaded.read(MAX_IMAGE_SIZE + 1)
    if len(data) > MAX_IMAGE_SIZE:
        return None, None, 'Зображення має бути не більше 5 МБ.'

    mimetype = uploaded.mimetype
    signatures = ALLOWED_IMAGE_TYPES.get(mimetype)
    valid = bool(signatures and any(data.startswith(sig) for sig in signatures))
    if mimetype == 'image/webp':
        valid = valid and len(data) >= 12 and data[8:12] == b'WEBP'

    if not valid:
        return None, None, 'Дозволені лише справжні зображення JPG, PNG, GIF або WEBP.'

    return data, mimetype, None


# ------------------------------------------------- замовлення та відгуки

@admin_bp.route('/')
def admin():
    return render_template(
        'admin.html',
        orders=models.get_orders(),
        feedback=models.get_feedback(),
    )


@admin_bp.route('/order/<int:order_id>')
def order_details(order_id):
    order, items = models.get_order_details(order_id)
    if order is None:
        abort(404)
    return render_template(
        'order_details.html', order=order, items=items, statuses=models.ORDER_STATUSES
    )


@admin_bp.route('/order/<int:order_id>/status', methods=['POST'])
def update_order(order_id):
    try:
        models.update_order_status(order_id, request.form.get('status', ''))
        flash(f'Статус замовлення №{order_id} оновлено.', 'success')
    except ValueError:
        flash('Невідомий статус замовлення.', 'error')
    return redirect(url_for('admin.order_details', order_id=order_id))


@admin_bp.route('/order/<int:order_id>/delete', methods=['POST'])
def delete_order(order_id):
    models.delete_order(order_id)
    flash(f'Замовлення №{order_id} видалено.', 'success')
    return redirect(url_for('admin.admin'))


@admin_bp.route('/feedback/<int:feedback_id>/delete', methods=['POST'])
def delete_feedback(feedback_id):
    models.delete_feedback(feedback_id)
    flash('Відгук видалено.', 'success')
    return redirect(url_for('admin.admin'))


# ------------------------------------------------------------- товари

def read_product_form():
    """Читає й перевіряє форму товару. Повертає (дані, помилка)."""
    name = request.form.get('name', '').strip()
    image = request.form.get('image', '').strip()
    try:
        price = round(float(request.form.get('price', '').replace(',', '.')), 2)
    except ValueError:
        return None, 'Ціна має бути числом.'
    if not name:
        return None, 'Вкажіть назву товару.'
    if price < 0:
        return None, 'Ціна не може бути від\'ємною.'
    image_data, image_mimetype, image_error = read_uploaded_image()
    if image_error:
        return None, image_error
    return {
        'name': name,
        'price': price,
        'image': image,
        'image_data': image_data,
        'image_mimetype': image_mimetype,
    }, None


@admin_bp.route('/products')
def products():
    return render_template('admin_products.html', products=models.get_products())


@admin_bp.route('/products/new', methods=['GET', 'POST'])
def new_product():
    if request.method == 'POST':
        data, error = read_product_form()
        if error is None:
            models.add_product(**data)
            flash(f'Товар «{data["name"]}» додано.', 'success')
            return redirect(url_for('admin.products'))
        flash(error, 'error')
    return render_template('product_form.html', product=request.form.to_dict(), is_new=True)


@admin_bp.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
def edit_product(product_id):
    product = models.get_product(product_id)
    if product is None:
        abort(404)
    product = dict(product)
    if request.method == 'POST':
        data, error = read_product_form()
        if error is None:
            models.update_product(product_id, **data)
            flash(f'Товар «{data["name"]}» оновлено.', 'success')
            return redirect(url_for('admin.products'))
        flash(error, 'error')
        product = request.form.to_dict()  # показуємо форму з тим, що ввів користувач
    return render_template('product_form.html', product=product, is_new=False)


@admin_bp.route('/products/<int:product_id>/delete', methods=['POST'])
def delete_product(product_id):
    try:
        models.delete_product(product_id)
        flash('Товар видалено.', 'success')
    except sqlite3.IntegrityError:
        # Спрацював зовнішній ключ: товар є в існуючих замовленнях
        flash('Не можна видалити товар, який є в замовленнях.', 'error')
    return redirect(url_for('admin.products'))
