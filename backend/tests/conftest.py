"""Shared pytest fixtures: isolated database, API client, sample notes."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Generator
from datetime import date, timedelta
from pathlib import Path

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-production")
_TMP = Path(tempfile.mkdtemp(prefix="sie-test-"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(_TMP / 'test.db').as_posix()}")
os.environ.setdefault("STORAGE_DIR", str(_TMP / "storage"))
os.environ.setdefault("GEMINI_API_KEY", "")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.models import Base  # noqa: E402
from app.db.session import SessionLocal, engine, get_db  # noqa: E402
from app.main import app  # noqa: E402

SAMPLE_NOTES = """Operating Systems
Chapter 1: Introduction to Operating Systems

An operating system is defined as a set of programs that manage computer
hardware and provide services to other programs. The kernel is the core
component that schedules processes, allocates memory and handles interrupts.
Everything above the kernel - the shell, the file manager, the compiler driver -
depends on those two responsibilities being correct.

Process: A program in execution. Each process has its own virtual address space,
its own open file descriptors and its own priority. A thread is a lightweight
execution context that shares an address space with sibling threads.

Why an operating system exists at all: the hardware is a bare machine, and every
program would otherwise have to talk to the device registers directly. The OS
abstracts that hardware behind a stable interface, which is why an application
written once runs on many different machines.

Chapter 2: Process Management and Scheduling

Scheduling is the process of deciding which process runs on the CPU at any
instant. Preemptive scheduling allows the operating system to interrupt a running
process, which improves responsiveness but introduces context switch overhead.

Algorithm: The scheduling algorithm must minimise average waiting time while
keeping throughput high and starvation bounded.
Step 1: Build the ready queue from processes in the ready state.
Step 2: Select the next process using the priority value.
Step 3: Dispatch the selected process to the CPU.
Finally, decrement the time slice and requeue the process if it has not finished.

The classic scheduling algorithms differ mainly in their response to a burst of
ready processes. First Come First Served is simple and fair in arrival order but
suffers badly from the convoy effect, where one long process blocks every short
one behind it. Shortest Job First minimises average waiting time but requires
knowing the burst length in advance, which is usually impossible.

Round Robin Time Quantum: T = q/n where n is the number of processes in the ready
queue and q is the configured time quantum. Choosing q is the central trade-off:
too small and the system spends its time on context switches, too large and the
response time degrades towards First Come First Served.

Priority scheduling assigns each process a static or dynamic priority and always
runs the highest priority ready process. It is the mechanism behind real-time
systems, where missing a deadline is a correctness failure rather than a
disappointment. Starvation is the classic failure mode, and the aging technique -
gradually boosting the priority of long-waiting processes - is the standard fix.

Chapter 3: Memory Management

Virtual memory allows a program to execute even when it is larger than the
physical memory installed in the machine. The distinction between the virtual
addresses a process issues and the physical addresses the DRAM returns is what
makes this possible.

Paging divides the virtual address space into fixed-size pages and physical
memory into equally sized frames. The page table is the data structure that maps
virtual page numbers onto frame numbers, and because the mapping need not be
contiguous, external fragmentation is eliminated entirely.

A page fault occurs when a referenced page is not currently resident in a frame.
The service routine must locate the page on secondary storage, read it into a
free frame, update the page table entry, and finally restart the faulting
instruction. Because that instruction is re-executed, the process pays both the
memory access and the page fault cost.

Approximate memory access time: memory access time = (1 - p) * ma + p * page
fault time, where p is the page fault rate, ma is the cost of a normal memory
access, and page fault time is dominated by disk seek and rotational latency.
TLB miss handling sits in the same path: the translation lookaside buffer caches
recent translations so that most page table walks are avoided entirely.

Replacement policies decide which resident page to evict under pressure. Optimal
is unobtainable in practice but serves as the benchmark for comparison.
Least Recently Used approximates recency and is simple to implement with a stack,
but it suffers from Belady's anomaly, where adding frames can increase the fault
count. Clock, or second chance, is the pragmatic compromise used in real systems.

Chapter 4: Deadlocks and Avoidance

A deadlock is a set of processes that are blocked forever, each waiting on an
event that only another member of the set can cause. Because no process in the set
can proceed, the condition is permanent without intervention.

The four necessary conditions are mutual exclusion, hold and wait, no preemption
and circular wait. Coffman conditions are essential for the exam, and all four
must hold simultaneously for a deadlock to be possible. Breaking any single
condition is sufficient to prevent deadlock.

Prevention and avoidance are different strategies. Prevention is pessimistic: it
removes one of the four necessary conditions by fiat, for example by requiring
that a process request all of its resources at once. Avoidance is optimistic: it
requires the system to know the future resource requests and admits a request
only when a safe state remains reachable.

Banker's algorithm is the classic avoidance technique. It maintains the concept of
a safe state, and grants a request only if the resulting state is still safe, by
searching for an ordering in which every process can eventually complete. The
algorithm is correct but its worst case cost is polynomial in the number of
processes, so it is not used in general-purpose production kernels.

Chapter 5: File Systems

A file system is a method of storing and organising data on a persistent storage
device behind a uniform interface of files and directories. The abstraction hides
the block addressing of the underlying device, which is what allows a file to be
copied between devices with entirely different geometry.

Inodes store the metadata for a file: its size, ownership, permissions, timestamps
and the list of block addresses. The directory is itself a file whose contents map
names onto inode numbers, which is why hard links work and why deleting a name
does not necessarily free the blocks.

Free space management has two classic approaches. The linked free list stores a
pointer to the next free block inside each free block, which is cheap to update
but degenerate for allocation. The free bit map stores one bit per block, which
makes both allocation and free-list construction fast, at the cost of one bit per
block of storage overhead.

Disk scheduling is dominated by seek time, because moving the head costs far more
than reading a block once the head is in position. First Come First Served
reorders nothing and is therefore both simple and unfair. Shortest Seek Time
prioritises the closest request but is not starvation free. SCAN, or the elevator
algorithm, sweeps the head across the full range of cylinders in one direction
and reverses at the end, which bounds worst-case wait to roughly twice the
full-sweep time and guarantees fairness.
"""

DATABASE_NOTES = """Database Systems

Unit 1: Relational Model and SQL

A relation is defined as a set of tuples over a fixed schema. The relational model
is declarative: the student states what is wanted, not how to obtain it.

A primary key uniquely identifies a tuple and is never null. A foreign key
references a candidate key in another relation, which is how referential integrity
is enforced. Normalisation removes redundancy: first normal form forbids repeating
groups, second normal form removes partial dependency on a composite key, and
third normal form removes transitive dependency.

Step 1: Identify the functional dependencies in the schema.
Step 2: Choose a candidate key for each relation.
Step 3: Decompose until no attribute depends transitively on a key.
Finally, verify that the decomposition is lossless and dependency preserving.

Unit 2: Query Processing and Indexing

A query plan is a tree the optimiser chooses to execute a declarative query. Cost
estimation relies on statistics about cardinality and selectivity, so a stale
statistic can make the optimiser choose a plan that is orders of magnitude worse.

An index is a redundant data structure that trades write cost and storage for read
speed. A B-tree index gives logarithmic search and is the default for range scans.
A hash index gives constant time equality lookup but cannot answer range queries.
Covering indexes include the selected columns so the query never touches the heap.

The classic join algorithms are nested loop, sort-merge and hash join. Nested loop
is quadratic in the outer relation unless an index is available on the inner one.
The optimal choice depends on estimated cardinality, which is why the optimiser
needs statistics to be correct.
"""


@pytest.fixture(autouse=True)
def _fresh_db() -> Generator[None, None, None]:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def register(
    client: TestClient, email: str = "student@example.com", name: str = "Test Student"
) -> dict:
    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "full_name": name,
            "password": "supersecret123",
            "daily_minutes": 120,
            "preferred_start_time": "18:00",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def account(client: TestClient) -> dict:
    return register(client)


@pytest.fixture
def headers(account: dict) -> dict[str, str]:
    return auth_headers(account["access_token"])


@pytest.fixture
def notes_file() -> bytes:
    return SAMPLE_NOTES.encode("utf-8")


@pytest.fixture
def subject(client: TestClient, headers: dict, notes_file: bytes) -> dict:
    created = client.post(
        "/api/subjects",
        headers=headers,
        json={
            "name": "Operating Systems",
            "code": "CS301",
            "knowledge_level": "beginner",
            "study_mode": "fast_exam",
            "exam_date": (date.today() + timedelta(days=21)).isoformat(),
            "daily_minutes": 120,
            "start_time": "18:00",
        },
    )
    assert created.status_code == 201, created.text
    subject_data = created.json()

    uploaded = client.post(
        f"/api/subjects/{subject_data['id']}/documents",
        headers=headers,
        files={"file": ("os_notes.txt", notes_file, "text/plain")},
        data={"analyze_now": "false", "use_llm": "false"},
    )
    assert uploaded.status_code == 201, uploaded.text
    return subject_data


@pytest.fixture
def analysed_subject(client: TestClient, headers: dict, subject: dict) -> dict:
    response = client.post(
        f"/api/subjects/{subject['id']}/analyze", headers=headers, params={"use_llm": "false"}
    )
    assert response.status_code == 200, response.text
    return subject


@pytest.fixture
def packaged_subject(client: TestClient, headers: dict, analysed_subject: dict) -> dict:
    response = client.post(f"/api/subjects/{analysed_subject['id']}/packages", headers=headers)
    assert response.status_code == 201, response.text
    return analysed_subject


@pytest.fixture
def planned_subject(client: TestClient, headers: dict, packaged_subject: dict) -> dict:
    response = client.post(
        f"/api/subjects/{packaged_subject['id']}/plan",
        headers=headers,
        json={"horizon_days": 14, "include_revision": True},
    )
    assert response.status_code == 201, response.text
    return packaged_subject
