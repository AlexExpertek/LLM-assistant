# LLM-assistant

#Устанавливаем Docker (на чистый Ubuntu 22/04)
curl -fsSL https://get.docker.com | sh
#Добавляем пользователя в группу docker
sudo usermod -aG docker $USER
newrp docker
#проверяем
docker --version
docker compose version

#Загружаем код на сервер
git clone https://github.com/AlexExpertek/LLM-assistant.git
cd tender-platform

#Заполняем .env
cp .env.example .env
nano .env
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
YANDEX_API_KEY
YANDEX_FOLDER_ID

#Запуск
mkdir -p storage
docker compose up --build -d
docker compose logs -f app
docker compose logs -f celery_worker

#Создаем таблицы в БД
docker compose exec app alembic init migrations
docker compose exec app alembic revision --autogenerate -m "initial"
docker compose exec app alembic upgrade head

#Открыть порты наружу
№Security Groups порты 8000(API); 5555(Flower).

№Проверка
curl http://localhost:8000/health
#Открыть в браузере
http://(IP):8000/docs
http://(IP):5555
