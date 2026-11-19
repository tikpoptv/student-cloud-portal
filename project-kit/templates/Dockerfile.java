# Java (Spring Boot / Maven) - set server.port=${PORT:8080} in application.properties
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /src
COPY pom.xml .
RUN mvn -q -B dependency:go-offline
COPY src ./src
RUN mvn -q -B package -DskipTests && cp target/*.jar /app.jar

FROM eclipse-temurin:21-jre
WORKDIR /app
RUN useradd --system --uid 10001 --create-home app && chown app:app /app
COPY --from=build --chown=app:app /app.jar /app/app.jar
ENV PORT=8080 JAVA_TOOL_OPTIONS="-XX:MaxRAMPercentage=75"
EXPOSE 8080
USER app
CMD ["java", "-jar", "/app/app.jar"]
