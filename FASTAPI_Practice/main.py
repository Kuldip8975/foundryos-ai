from fastapi import FastAPI

app = FastAPI()

@app.get("/users")
def get_users():
    return [{"id": 1, "name": "Amit"}]

@app.post("/users")
def create_user():
    return {"message": "User created"}

@app.delete("/users/{user_id}")
def delete_user(user_id: int):
    return {"deleted_user_id": user_id}