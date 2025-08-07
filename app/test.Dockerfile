 # download a base version of node from Docker Hub
FROM node:14 as build-stage

# Set the working directory install and build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY ./ .
RUN npm run build --dev --configuration=dev


# Stage 2: Serve app with nginx server

# Use official nginx image as the base image
FROM nginx:alpine as production-stage
RUN mkdir /app
COPY --from=build-stage /app/dist/uni-app /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf


# Copy the build output to replace the default nginx contents.
#COPY --from=build /code/app/dist/uni-app /usr/share/nginx/html

# # Containers run nginx with global directives and daemon off
# ENTRYPOINT ["nginx", "-g", "daemon off;"]

# # Expose port 80
#EXPOSE 80

