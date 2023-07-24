# Copyright 2023 The Matrix.org Foundation C.I.C.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from synapse.storage._base import SQLBaseStore
from synapse.storage.database import (
    DatabasePool,
    LoggingDatabaseConnection,
    LoggingTransaction,
    make_in_list_sql_clause,
)
from synapse.types import JsonDict, JsonMapping, ScheduledTask, TaskStatus

if TYPE_CHECKING:
    from synapse.server import HomeServer


class TaskSchedulerWorkerStore(SQLBaseStore):
    def __init__(
        self,
        database: DatabasePool,
        db_conn: LoggingDatabaseConnection,
        hs: "HomeServer",
    ):
        super().__init__(database, db_conn, hs)

    @staticmethod
    def _convert_row_to_task(row: Dict[str, Any]) -> ScheduledTask:
        row["status"] = TaskStatus(row["status"])
        if row["params"] is not None:
            row["params"] = json.loads(row["params"])
        if row["result"] is not None:
            row["result"] = json.loads(row["result"])
        return ScheduledTask(**row)

    async def get_scheduled_tasks(
        self,
        actions: Optional[List[str]] = None,
        resource_ids: Optional[List[str]] = None,
        statuses: Optional[List[TaskStatus]] = None,
    ) -> List[ScheduledTask]:
        """Get a list of scheduled tasks from the DB.

        If an arg is `None` all tasks matching the other args will be selected.
        If an arg is an empty list, the value needs to be NULL in DB to be selected.

        Args:
            actions: Limit the returned tasks to those specific action names
            resource_ids: Limit the returned tasks to thoe specific resource ids
            statuses: Limit the returned tasks to thoe specific statuses

        Returns: a list of `ScheduledTask`
        """

        def get_scheduled_tasks_txn(txn: LoggingTransaction) -> List[Dict[str, Any]]:
            clauses = []
            args = []
            if actions is not None:
                clause, temp_args = make_in_list_sql_clause(
                    txn.database_engine, "action", actions
                )
                clauses.append(clause)
                args.extend(temp_args)
            if resource_ids is not None:
                clause, temp_args = make_in_list_sql_clause(
                    txn.database_engine, "resource_id", resource_ids
                )
                clauses.append(clause)
                args.extend(temp_args)
            if statuses is not None:
                clause, temp_args = make_in_list_sql_clause(
                    txn.database_engine, "status", statuses
                )
                clauses.append(clause)
                args.extend(temp_args)

            sql = "SELECT * FROM scheduled_tasks"
            if clauses:
                sql = sql + " WHERE " + " AND ".join(clauses)

            txn.execute(sql, args)
            return self.db_pool.cursor_to_dict(txn)

        rows = await self.db_pool.runInteraction(
            "get_scheduled_tasks", get_scheduled_tasks_txn
        )
        return [TaskSchedulerWorkerStore._convert_row_to_task(row) for row in rows]

    async def upsert_scheduled_task(self, task: ScheduledTask) -> None:
        """Upsert a specified `ScheduledTask` in the DB.

        Args:
            task: the `ScheduledTask` to upsert
        """
        await self.db_pool.simple_upsert(
            "scheduled_tasks",
            {"id": task.id},
            {
                "action": task.action,
                "status": task.status,
                "timestamp": task.timestamp,
                "resource_id": task.resource_id,
                "params": None if task.params is None else json.dumps(task.params),
                "result": None if task.result is None else json.dumps(task.result),
                "error": task.error,
            },
            desc="upsert_scheduled_task",
        )

    async def update_scheduled_task(
        self,
        id: str,
        *,
        timestamp: Optional[int] = None,
        status: Optional[TaskStatus] = None,
        result: Optional[JsonMapping] = None,
        error: Optional[str] = None,
    ) -> bool:
        """Update a scheduled task in the DB with some new value(s).

        Args:
            id: id of the `ScheduledTask` to update
            timestamp: new timestamp of the task
            status: new status of the task
            result: new result of the task
            error: new error of the task
        """
        updatevalues: JsonDict = {}
        if timestamp is not None:
            updatevalues["timestamp"] = timestamp
        if status is not None:
            updatevalues["status"] = status
        if result is not None:
            updatevalues["result"] = json.dumps(result)
        if error is not None:
            updatevalues["error"] = error
        nb_rows = await self.db_pool.simple_update(
            "scheduled_tasks",
            {"id": id},
            updatevalues,
            desc="update_scheduled_task",
        )
        return nb_rows > 0

    async def get_scheduled_task(self, id: str) -> Optional[ScheduledTask]:
        """Get a specific `ScheduledTask` from its id.

        Args:
            id: the id of the task to retrieve

        Returns: the task if available, `None` otherwise
        """
        row = await self.db_pool.simple_select_one(
            table="scheduled_tasks",
            keyvalues={"id": id},
            retcols=(
                "id",
                "action",
                "status",
                "timestamp",
                "resource_id",
                "params",
                "result",
                "error",
            ),
            allow_none=True,
            desc="get_scheduled_task",
        )

        return TaskSchedulerWorkerStore._convert_row_to_task(row) if row else None

    async def delete_scheduled_task(self, id: str) -> None:
        """Delete a specific task from its id.

        Args:
            id: the id of the task to delete
        """
        await self.db_pool.simple_delete(
            "scheduled_tasks",
            keyvalues={"id": id},
            desc="delete_scheduled_task",
        )