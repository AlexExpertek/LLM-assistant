# LLM-assistant

#Подключаемся к VM
ssh -i C:\\user\....\ user@(ip)

#Устанавливаем Docker (на чистый Ubuntu 22/04)
curl -fsSL https://get.docker.com | sh
#Добавляем пользователя в группу docker
sudo usermod -aG docker $USER
newgrp docker
#проверяем
docker --version
docker compose version

#Загружаем код на сервер
git clone https://github.com/AlexExpertek/LLM-assistant.git
cd LLM-assistant
tar -xzf tender-ai-platform.tar.gz
cd tender-platform

#Заполняем .env
cp .env.example .env
nano .env
#Вписать:
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
YANDEX_API_KEY
YANDEX_FOLDER_ID

#Проверка PostgreSQL
docker compose ps

#Подклиться к PostgreSQL
docker compose exec postgres psql -U tender_user -d tender_db

#Создаем таблицы в БД
docker compose exec app alembic init migrations
docker compose exec app alembic upgrade head
docker compose exec app alembic revision --autogenerate -m "initial"

#Проверяем таблицы
docker compose exec postgres psql -U tender_user -d tender_db -c "\dt"

#Запуск
mkdir -p storage
docker compose up --build -d
docker compose logs -f app
docker compose logs -f celery_worker

#Удалить CHANGE_ME
#Открыть файл .env и уделить CHANGE_ME из комментариев

#Запуск-2
chmod +x scripts/install.sh
./scripts/install.sh



#Открыть порты наружу
№Security Groups порты 8000(API); 5555(Flower).

#Открыть порты на ружу
docker-compose.yml
  app:
      - "8000:8000"
  app:
      - "5555:5555"

№Проверка
curl http://localhost:8000/health
#Открыть в браузере
http://(IP):8000/docs
http://(IP):5555

#Отключение автоматического сканирования тендеров
docker compose stop celery_beat

#Включение автоматического сканирования тендеров
docker compose start celery_beat

