# Static frontend - plain HTML/CSS/JS served by nginx. There's no build
# step and no server-side code: the browser talks to the FastAPI backend
# directly (see api.js), which is why this is just a file server.
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf

WORKDIR /usr/share/nginx/html
# Only the static app - deliberately explicit rather than `COPY . .`, so
# stray files in this directory never end up published by the web server.
COPY index.html login.html register.html ./
COPY api.js app.js style.css ./
