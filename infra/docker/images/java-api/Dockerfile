FROM maven:3.9.9-eclipse-temurin-21 AS build
WORKDIR /src
COPY server-java/pom.xml ./server-java/pom.xml
COPY server-java/src ./server-java/src
COPY assets/eval ./assets/eval
WORKDIR /src/server-java
RUN mvn -q -DskipTests package

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /src/server-java/target/xiaoyi-rag-server-0.1.0-SNAPSHOT.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
