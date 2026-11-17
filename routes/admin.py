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
    """Перевіряє завантажене зображення та повертає його дані."""

    uploaded = request.files.get('image_file')

    if uploaded is None or not uploaded.filename:
        return None, None, None

    data = uploaded.read(MAX_IMAGE_SIZE + 1)

    if len(data) > MAX_IMAGE_SIZE:
        return None, None, 'Зображення має бути не більше 5 МБ.'

    # Визначаємо формат за справжньою сигнатурою файлу
    if data.startswith(b'\xff\xd8\xff'):
        mimetype = 'image/jpeg'

    elif data.startswith(b'\x89PNG\r\n\x1a\n'):
        mimetype = 'image/png'

    elif data.startswith((b'GIF87a', b'GIF89a')):
        mimetype = 'image/gif'

    elif len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        mimetype = 'image/webp'

    else:
        return None, None, 'Дозволені лише справжні зображення JPG, PNG, GIF або WEBP.'

    return data, mimetype, None

@admin_bp.errorhandler(413)
def request_entity_too_large(error):
    flash('Файл завеликий. Максимальний розмір зображення — 5 МБ.', 'error')
    return redirect(url_for('admin.products'))

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
    try:
        discount_percent = round(float(request.form.get('discount_percent', '0').replace(',', '.')), 2)
    except ValueError:
        return None, 'Знижка має бути числом.'
    if discount_percent < 0 or discount_percent > 100:
        return None, 'Знижка має бути в межах від 0 до 100%.'
    try:
        category_id = int(request.form.get('category_id')) if request.form.get('category_id') else None
    except ValueError:
        category_id = None
    if category_id is not None and models.get_category(category_id) is None:
        return None, 'Невідома категорія.'
    image_data, image_mimetype, image_error = read_uploaded_image()
    if image_error:
        return None, image_error
    return {
        'name': name,
        'price': price,
        'image': image,
        'image_data': image_data,
        'image_mimetype': image_mimetype,
        'discount_percent': discount_percent,
        'category_id': category_id,
    }, None


@admin_bp.route('/products')
def products():
    return render_template(
        'admin_products.html',
        products=models.get_products(),
        categories=models.get_categories(),
    )


@admin_bp.route('/products/new', methods=['GET', 'POST'])
def new_product():
    if request.method == 'POST':
        data, error = read_product_form()
        if error is None:
            models.add_product(**data)
            flash(f'Товар «{data["name"]}» додано.', 'success')
            return redirect(url_for('admin.products'))
        flash(error, 'error')
    return render_template(
        'product_form.html',
        product=request.form.to_dict(),
        categories=models.get_category_tree(),
        is_new=True,
    )


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
    return render_template(
        'product_form.html',
        product=product,
        categories=models.get_category_tree(),
        is_new=False,
    )


@admin_bp.route('/products/<int:product_id>/delete', methods=['POST'])
def delete_product(product_id):
    try:
        models.delete_product(product_id)
        flash('Товар видалено.', 'success')
    except sqlite3.IntegrityError:
        # Спрацював зовнішній ключ: товар є в існуючих замовленнях
        flash('Не можна видалити товар, який є в замовленнях.', 'error')
    return redirect(url_for('admin.products'))


# -------------------------------------------------------- категорії та промокоди

@admin_bp.route('/categories', methods=['GET', 'POST'])
def categories():
    if request.method == 'POST':
        try:
            parent_id = int(request.form.get('parent_id')) if request.form.get('parent_id') else None
            models.add_category(request.form.get('name', ''), parent_id)
            flash('Категорію додано.', 'success')
        except (ValueError, sqlite3.IntegrityError) as error:
            flash(str(error), 'error')
        return redirect(url_for('admin.categories'))
    return render_template(
        'admin_categories.html',
        categories=models.get_category_tree(),
        all_categories=models.get_categories(),
    )


@admin_bp.route('/categories/<int:category_id>/delete', methods=['POST'])
def delete_category(category_id):
    models.delete_category(category_id)
    flash('Категорію видалено.', 'success')
    return redirect(url_for('admin.categories'))


@admin_bp.route('/promocodes', methods=['GET', 'POST'])
def promocodes():
    if request.method == 'POST':
        try:
            percent = float(request.form.get('discount_percent', '0').replace(',', '.'))
            amount = float(request.form.get('discount_amount', '0').replace(',', '.'))
            minimum = float(request.form.get('min_order', '0').replace(',', '.'))
            models.add_promocode(
                request.form.get('code', ''),
                discount_percent=percent,
                discount_amount=amount,
                min_order=minimum,
                active=request.form.get('active') == '1',
                expires_at=request.form.get('expires_at', '').strip() or None,
            )
            flash('Промокод створено.', 'success')
        except (ValueError, sqlite3.IntegrityError) as error:
            flash(str(error), 'error')
        return redirect(url_for('admin.promocodes'))
    return render_template('admin_promocodes.html', promocodes=models.get_promocodes())


@admin_bp.route('/promocodes/<int:promo_id>/delete', methods=['POST'])
def delete_promocode(promo_id):
    models.delete_promocode(promo_id)
    flash('Промокод видалено.', 'success')
    return redirect(url_for('admin.promocodes'))
