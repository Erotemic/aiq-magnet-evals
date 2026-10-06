FROM python:3.12-alpine@sha256:4c47124a8391cb7a9f571164147d154777cf012a4ece5f86097130d7a4478111
RUN apk add --no-cache bash git && pip install --no-cache-dir pytest==8.4.2
WORKDIR /app
COPY calc.py test_calc.py .gitignore /app/
RUN git init && git config user.email fixture@example.invalid && git config user.name Fixture \
    && git add . && git commit -m 'Synthetic benchmark base'
