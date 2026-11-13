from app import app
import models

if __name__ == '__main__':
    with app.app_context():
        models.init_db()
    print(f"База даних ініціалізована: {app.config['DATABASE']}")
