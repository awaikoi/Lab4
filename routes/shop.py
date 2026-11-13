from io import BytesIO

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for, send_file

import models

shop_bp = Blueprint('shop', __name__)

MAX_QUANTITY = 99


def get_cart():
    """Кошик у сесії: {id товару: кількість}. У сесії ключі зберігаються рядками."""
    return {int(pid): qty for pid, qty in session.get('cart', {}).items()}


def save_cart(cart):
    session['cart'] = {str(pid): qty for pid, qty in cart.items()}


def get_quantity():
    """Кількість із форми, обмежена діапазоном 0..MAX_QUANTITY."""
    try:
        quantity = int(request.form.get('quantity', 1))
    except ValueError:
        quantity = 1
    return max(0, min(quantity, MAX_QUANTITY))


def build_cart_lines():
    """Рядки кошика з актуальними даними товарів із бази (назва, ціна беруться звідти, а не з сесії)."""
    cart = get_cart()
    lines = [
        {'product': p, 'quantity': cart[p['id']], 'subtotal': round(p['price'] * cart[p['id']], 2)}
        for p in models.get_products_by_ids(cart.keys())
    ]
    # Якщо товар видалили з магазину, прибираємо його й з кошика
    if len(lines) != len(cart):
        save_cart({line['product']['id']: line['quantity'] for line in lines})
    return lines




@shop_bp.route('/products/<int:product_id>/image')
def product_image(product_id):
    """Віддає зображення товару, яке збережене в SQLite як BLOB."""
    product = models.get_product(product_id)
    if product is None:
        abort(404)
    if not product['image_data']:
        abort(404)
    return send_file(
        BytesIO(product['image_data']),
        mimetype=product['image_mimetype'] or 'application/octet-stream',
        max_age=3600,
    )

@shop_bp.route('/shop')
def shop():
    return render_template('shop.html', products=models.get_products())


@shop_bp.route('/cart/add/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    product = models.get_product(product_id)
    if product is None:
        flash('Такого товару не існує.', 'error')
        return redirect(url_for('shop.shop'))

    cart = get_cart()
    cart[product_id] = min(cart.get(product_id, 0) + 1, MAX_QUANTITY)
    save_cart(cart)
    flash(f'«{product["name"]}» додано до кошика.', 'success')
    return redirect(url_for('shop.shop'))


@shop_bp.route('/cart')
def cart():
    lines = build_cart_lines()
    total = round(sum(line['subtotal'] for line in lines), 2)
    return render_template('cart.html', lines=lines, total=total, max_quantity=MAX_QUANTITY)


@shop_bp.route('/cart/update/<int:product_id>', methods=['POST'])
def update_cart(product_id):
    cart = get_cart()
    if product_id in cart:
        quantity = get_quantity()
        if quantity == 0:
            del cart[product_id]
        else:
            cart[product_id] = quantity
        save_cart(cart)
    return redirect(url_for('shop.cart'))


@shop_bp.route('/cart/remove/<int:product_id>', methods=['POST'])
def remove_from_cart(product_id):
    cart = get_cart()
    cart.pop(product_id, None)
    save_cart(cart)
    return redirect(url_for('shop.cart'))


@shop_bp.route('/checkout', methods=['POST'])
def checkout():
    email = request.form.get('email', '').strip()
    address = request.form.get('address', '').strip()
    if '@' not in email or not address:
        flash('Вкажіть коректний email та адресу доставки.', 'error')
        return redirect(url_for('shop.cart'))

    try:
        order_id = models.create_order(email, address, get_cart())
    except ValueError:
        flash('Кошик порожній.', 'error')
        return redirect(url_for('shop.cart'))

    save_cart({})
    flash(f'Замовлення №{order_id} оформлено. Дякуємо!', 'success')
    return redirect(url_for('shop.shop'))
