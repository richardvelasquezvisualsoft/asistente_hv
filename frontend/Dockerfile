FROM nginx:alpine

# Copiar la configuración personalizada de Nginx
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copiar el archivo estático del frontend
COPY index.html /usr/share/nginx/html/index.html

# Exponer el puerto 3003 para el frontend
EXPOSE 3003

# Ejecutar Nginx en primer plano
CMD ["nginx", "-g", "daemon off;"]
