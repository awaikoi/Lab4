from flask import Blueprint, jsonify, render_template, request

import models

feedback_bp = Blueprint('feedback', __name__)


@feedback_bp.route('/feedback', methods=['GET', 'POST'])
def feedback():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        message = request.form.get('message', '').strip()

        # Перевірка на сервері обов'язкова: HTML-атрибут required легко обійти
        if not name or not message or '@' not in email:
            return jsonify({'error': 'Заповніть усі поля та вкажіть коректний email.'}), 400

        models.add_feedback(name, email, message)
        return jsonify({'status': 'success'}), 200

    return render_template('feedback.html')
