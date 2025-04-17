from fastapi import APIRouter
from dao import ModIndexDAO
from models import ModIndex

router = APIRouter()

@router.get("/mod_index", response_model=ModIndex)
def get_mod_index() -> ModIndex:
    return ModIndex(mods=ModIndexDAO.get_all_mods())