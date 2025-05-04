- [x] Step 1: Set Up TimescaleDB (via Docker) - Create a Docker Compose service for TimescaleDB: - Define the TimescaleDB container in docker-compose.yml. - Expose the necessary ports (default: 5432). - Mount a volume for persistent data storage.

        - Initialize the database schema:
            - Use the init.sql file to create the required tables (e.g., ohlcv_data, tracked_fvgs, etc.).

- [x] Step 2: Set Up Redis (Pub/Sub) - Add Redis to Docker Compose: - Define a Redis service in docker-compose.yml. - Expose the default Redis port (6379).

        - Test Redis locally:
            - Use a Python script with redis-py to publish and subscribe to a test channel.

- [x] Step 3: Set Up Prometheus + Grafana - Add Prometheus and Grafana to Docker Compose: - Define services for both Prometheus and Grafana. - Mount configuration files for Prometheus (e.g., prometheus.yaml).

        - Configure Prometheus:
            - Add Redis and TimescaleDB exporters to monitor their metrics.

        - Set up Grafana dashboards:
            - Import prebuilt dashboards for Redis and PostgreSQL or create custom ones.

- [x] Step 4: Create Shared .env and settings.yaml - Define environment variables in .env: - Include database credentials, Redis host/port, and other shared settings.

        - Create settings.yaml:
            - Store configuration for agents, such as timeframes, risk parameters, and API keys.

- [x] Step 5: Define Docker Compose for Multi-Agent Architecture - Add all services to docker-compose.yml: - Include TimescaleDB, Redis, Prometheus, Grafana, and placeholders for agents.

        - Test the setup:
            - Run docker-compose up and ensure all services start without errors.

- [x] 6.  Start the Services
      Run the updated docker-compose.yml to start Prometheus, Grafana, and the exporters:
      ```bash
          docker-compose up -d
      ```
- [x] 7. Access Prometheus and Grafana
     Prometheus:
     Open your browser and go to http://localhost:9090.
     Verify that Prometheus is running and scraping the defined targets.
     Grafana:
     Open your browser and go to http://localhost:3000.
     Log in with the default credentials (admin/admin).
     Change the password when prompted.
- [x] 8. Configure Grafana
     Add Prometheus as a Data Source:
     Go to Grafana → Configuration → Data Sources → Add Data Source.
     Select Prometheus and set the URL to http://prometheus:9090.
     Click Save & Test.
     Import Dashboards:
     Go to Grafana → Dashboards → Import.
     Use prebuilt dashboards for Redis and PostgreSQL:
     Redis Exporter Dashboard: Dashboard ID 763
     PostgreSQL Exporter Dashboard: Dashboard ID 9628
- [x] 9. Verify Metrics
     Check the Prometheus targets page (http://localhost:9090/targets) to ensure all targets (Prometheus, Redis, TimescaleDB) are being scraped.
     Open the Grafana dashboards to visualize metrics for Redis and TimescaleDB.
- [x] 8. Next Steps
     Once Prometheus and Grafana are set up and verified:
     We can move on to creating the shared .env and settings.yaml files for configuration.
     Let me know if you'd like to proceed or need help with any part of this setup! 🚀
