from fastapi import FastAPI
import state

app = FastAPI()

@app.get("/")
def home():
    return state.state