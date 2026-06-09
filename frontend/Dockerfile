# Dev-oriented image: runs the Vite dev server with hot-reload. The browser
# (on the host) calls the backend directly at http://localhost:8000, so no
# build-time API base is needed; CORS on the backend allows this origin.
FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
