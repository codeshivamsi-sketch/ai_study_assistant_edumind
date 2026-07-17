up:
	docker-compose up --build

down:
	docker-compose down

logs:
	docker-compose logs -f

proto:
	python3 -m grpc_tools.protoc -I proto --python_out=services/core-api --grpc_python_out=services/core-api proto/notifications.proto