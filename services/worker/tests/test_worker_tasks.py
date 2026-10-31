from mindnest_worker.tasks import ping


def test_ping_task_runs_inline() -> None:
    # Calling the task object directly runs it in-process, without a broker.
    assert ping() == "pong"
