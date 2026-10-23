"""Account-scoped HTTP adapters for exact Agent operation queries."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from project_path_service import project_or_404
from agent_api.errors import AgentAPIError
from agent_operation_service import AgentOperationDependencies, AgentOperationService, AgentOperationError
from agent_contract.operations import OperationResult, OperationListResult, OperationCancelResult
from one_click_orchestrator import get_one_click_run, list_one_click_runs
from generation_control import status, request_stop


router = APIRouter()
service = AgentOperationService(AgentOperationDependencies(
    pipeline_get=get_one_click_run, pipeline_list=list_one_click_runs,
    control_status=status, control_stop=request_stop,
))


def _call(action):
    try:
        return action()
    except AgentOperationError as exc:
        raise AgentAPIError(exc.code, exc.message, exc.status_code) from exc


@router.get("/projects/{project_id}/operations", response_model=OperationListResult)
def agent_list_operations(project_id: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
                          db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    return _call(lambda: service.list(db, project, offset=offset, limit=limit))


@router.get("/projects/{project_id}/operations/{operation_id}", response_model=OperationResult)
def agent_get_operation(project_id: str, operation_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    return _call(lambda: service.get(db, project, operation_id))


@router.post("/projects/{project_id}/operations/{operation_id}/cancel", response_model=OperationCancelResult)
def agent_cancel_operation(project_id: str, operation_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    return _call(lambda: service.cancel(db, project, operation_id))
