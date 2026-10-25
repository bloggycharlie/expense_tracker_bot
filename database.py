"""Database layer with Repository Pattern for Expense Tracking."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import aiosqlite
from config import DATABASE_PATH, DATABASE_URL

try:
    import asyncpg
except ImportError:
    asyncpg = None


@dataclass
class Expense:
    """Model representing a saved expense record."""
    id: int
    user_id: int
    amount: float
    category: str
    description: str
    date: str  # Format: YYYY-MM-DD
    raw_message: Optional[str] = None
    created_at: Optional[str] = None

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "Expense":
        """Construct an Expense instance from a database row."""
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            amount=row["amount"],
            category=row["category"],
            description=row["description"],
            date=row["date"],
            raw_message=row["raw_message"],
            created_at=row["created_at"],
        )


class BaseExpenseRepository(ABC):
    """Abstract interface defining the repository contract for expense storage."""

    @abstractmethod
    async def init_db(self) -> None:
        """Initialize the storage schema/tables."""
        pass

    @abstractmethod
    async def add_expense(
        self,
        user_id: int,
        amount: float,
        category: str,
        description: str,
        date: str,
        raw_message: Optional[str] = None,
    ) -> int:
        """Add a single expense record and return its generated ID."""
        pass

    @abstractmethod
    async def add_expenses(
        self,
        user_id: int,
        items: List[Dict[str, Any]],
        raw_message: Optional[str] = None,
    ) -> List[int]:
        """Add multiple expense records in a single batch and return their IDs."""
        pass

    @abstractmethod
    async def get_expense_by_id(self, expense_id: int, user_id: int) -> Optional[Expense]:
        """Fetch a single expense by ID belonging to user_id."""
        pass

    @abstractmethod
    async def delete_expense(self, expense_id: int, user_id: int) -> bool:
        """Delete an expense by ID belonging to user_id."""
        pass

    @abstractmethod
    async def delete_expenses(self, expense_ids: List[int], user_id: int) -> int:
        """Delete multiple expenses belonging to user_id and return count deleted."""
        pass

    @abstractmethod
    async def get_expenses_by_date(self, user_id: int, date_str: str) -> List[Expense]:
        """Retrieve all expenses for a specific date (YYYY-MM-DD)."""
        pass

    @abstractmethod
    async def get_recent_expenses(self, user_id: int, limit: int = 10) -> List[Expense]:
        """Retrieve recent expenses for a user ordered by newest first."""
        pass

    @abstractmethod
    async def get_daily_summary(self, user_id: int, date_str: str) -> Dict[str, Any]:
        """Calculate daily spending total and category breakdown."""
        pass

    @abstractmethod
    async def get_monthly_summary(self, user_id: int, year: int, month: int) -> Dict[str, Any]:
        """Calculate monthly spending total and category breakdown."""
        pass

    @abstractmethod
    async def set_budget(self, user_id: int, amount: float) -> None:
        """Set overall monthly budget limit for a user."""
        pass

    @abstractmethod
    async def get_budget(self, user_id: int) -> Optional[float]:
        """Retrieve monthly budget limit for a user, if configured."""
        pass

    @abstractmethod
    async def set_category_budget(self, user_id: int, category: str, amount: float) -> None:
        """Set budget limit for a specific category."""
        pass

    @abstractmethod
    async def get_category_budgets(self, user_id: int) -> Dict[str, float]:
        """Retrieve all category budgets configured for a user."""
        pass

    @abstractmethod
    async def get_category_budget(self, user_id: int, category: str) -> Optional[float]:
        """Retrieve budget limit for a specific category."""
        pass

    @abstractmethod
    async def clear_category_budgets(self, user_id: int) -> None:
        """Clear all category and overall budgets for a user."""
        pass

    @abstractmethod
    async def get_all_expenses(
        self, user_id: int, year: Optional[int] = None, month: Optional[int] = None
    ) -> List[Expense]:
        """Retrieve all expenses, optionally filtered by month, ordered by date desc."""
        pass


class SQLiteExpenseRepository(BaseExpenseRepository):
    """SQLite implementation of BaseExpenseRepository using async aiosqlite."""

    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path

    async def init_db(self) -> None:
        """Create tables and indices if they do not exist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    date TEXT NOT NULL,
                    raw_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS budgets (
                    user_id INTEGER PRIMARY KEY,
                    monthly_budget REAL NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS category_budgets (
                    user_id INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    amount REAL NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, category)
                );
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_expenses_user_date ON expenses (user_id, date);"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_expenses_created ON expenses (created_at);"
            )
            await db.commit()

    async def add_expense(
        self,
        user_id: int,
        amount: float,
        category: str,
        description: str,
        date: str,
        raw_message: Optional[str] = None,
    ) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO expenses (user_id, amount, category, description, date, raw_message)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, amount, category, description, date, raw_message),
            )
            await db.commit()
            return cursor.lastrowid or 0

    async def add_expenses(
        self,
        user_id: int,
        items: List[Dict[str, Any]],
        raw_message: Optional[str] = None,
    ) -> List[int]:
        if not items:
            return []

        inserted_ids = []
        async with aiosqlite.connect(self.db_path) as db:
            for item in items:
                cursor = await db.execute(
                    """
                    INSERT INTO expenses (user_id, amount, category, description, date, raw_message)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        item["amount"],
                        item["category"],
                        item["description"],
                        item["date"],
                        raw_message,
                    ),
                )
                if cursor.lastrowid is not None:
                    inserted_ids.append(cursor.lastrowid)
            await db.commit()
        return inserted_ids

    async def get_expense_by_id(self, expense_id: int, user_id: int) -> Optional[Expense]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM expenses WHERE id = ? AND user_id = ?",
                (expense_id, user_id),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return Expense.from_row(row)
        return None

    async def delete_expense(self, expense_id: int, user_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM expenses WHERE id = ? AND user_id = ?",
                (expense_id, user_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def delete_expenses(self, expense_ids: List[int], user_id: int) -> int:
        if not expense_ids:
            return 0
        placeholders = ",".join("?" for _ in expense_ids)
        params = list(expense_ids) + [user_id]
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                f"DELETE FROM expenses WHERE id IN ({placeholders}) AND user_id = ?",
                params,
            )
            await db.commit()
            return cursor.rowcount

    async def get_expenses_by_date(self, user_id: int, date_str: str) -> List[Expense]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM expenses WHERE user_id = ? AND date = ? ORDER BY id ASC",
                (user_id, date_str),
            ) as cursor:
                rows = await cursor.fetchall()
                return [Expense.from_row(row) for row in rows]

    async def get_recent_expenses(self, user_id: int, limit: int = 10) -> List[Expense]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM expenses WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ) as cursor:
                rows = await cursor.fetchall()
                return [Expense.from_row(row) for row in rows]

    async def get_daily_summary(self, user_id: int, date_str: str) -> Dict[str, Any]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # Total and count
            async with db.execute(
                "SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS count FROM expenses WHERE user_id = ? AND date = ?",
                (user_id, date_str),
            ) as cursor:
                agg = await cursor.fetchone()
                total = agg["total"] if agg else 0.0
                count = agg["count"] if agg else 0

            # Breakdown by category
            async with db.execute(
                """
                SELECT category, SUM(amount) AS cat_total, COUNT(*) AS cat_count
                FROM expenses
                WHERE user_id = ? AND date = ?
                GROUP BY category
                ORDER BY cat_total DESC
                """,
                (user_id, date_str),
            ) as cursor:
                categories = await cursor.fetchall()

        return {
            "date": date_str,
            "total": total,
            "count": count,
            "categories": [
                {
                    "category": row["category"],
                    "total": row["cat_total"],
                    "count": row["cat_count"],
                }
                for row in categories
            ],
        }

    async def get_monthly_summary(self, user_id: int, year: int, month: int) -> Dict[str, Any]:
        month_prefix = f"{year:04d}-{month:02d}-%"
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # Total and count
            async with db.execute(
                "SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS count FROM expenses WHERE user_id = ? AND date LIKE ?",
                (user_id, month_prefix),
            ) as cursor:
                agg = await cursor.fetchone()
                total = agg["total"] if agg else 0.0
                count = agg["count"] if agg else 0

            # Breakdown by category
            async with db.execute(
                """
                SELECT category, SUM(amount) AS cat_total, COUNT(*) AS cat_count
                FROM expenses
                WHERE user_id = ? AND date LIKE ?
                GROUP BY category
                ORDER BY cat_total DESC
                """,
                (user_id, month_prefix),
            ) as cursor:
                categories = await cursor.fetchall()

        return {
            "year": year,
            "month": month,
            "total": total,
            "count": count,
            "categories": [
                {
                    "category": row["category"],
                    "total": row["cat_total"],
                    "count": row["cat_count"],
                }
                for row in categories
            ],
        }

    async def set_budget(self, user_id: int, amount: float) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO budgets (user_id, monthly_budget, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    monthly_budget = excluded.monthly_budget,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, amount),
            )
            await db.commit()

    async def get_budget(self, user_id: int) -> Optional[float]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT monthly_budget FROM budgets WHERE user_id = ?",
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row and float(row[0]) > 0:
                    return float(row[0])
            # If total budget is not explicitly set, sum all category budgets if present
            async with db.execute(
                "SELECT SUM(amount) FROM category_budgets WHERE user_id = ?",
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row and row[0] is not None and float(row[0]) > 0:
                    return float(row[0])
                return None

    async def set_category_budget(self, user_id: int, category: str, amount: float) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            if amount <= 0:
                await db.execute(
                    "DELETE FROM category_budgets WHERE user_id = ? AND category = ?",
                    (user_id, category),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO category_budgets (user_id, category, amount, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id, category) DO UPDATE SET
                        amount = excluded.amount,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (user_id, category, float(amount)),
                )
            await db.commit()

    async def get_category_budgets(self, user_id: int) -> Dict[str, float]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT category, amount FROM category_budgets WHERE user_id = ?",
                (user_id,),
            ) as cursor:
                rows = await cursor.fetchall()
                return {r[0]: float(r[1]) for r in rows}

    async def get_category_budget(self, user_id: int, category: str) -> Optional[float]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT amount FROM category_budgets WHERE user_id = ? AND category = ?",
                (user_id, category),
            ) as cursor:
                row = await cursor.fetchone()
                return float(row[0]) if row else None

    async def clear_category_budgets(self, user_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM category_budgets WHERE user_id = ?", (user_id,))
            await db.execute("DELETE FROM budgets WHERE user_id = ?", (user_id,))
            await db.commit()

    async def get_all_expenses(
        self, user_id: int, year: Optional[int] = None, month: Optional[int] = None
    ) -> List[Expense]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if year and month:
                prefix = f"{year:04d}-{month:02d}-%"
                query = "SELECT * FROM expenses WHERE user_id = ? AND date LIKE ? ORDER BY date DESC, id DESC"
                params = (user_id, prefix)
            else:
                query = "SELECT * FROM expenses WHERE user_id = ? ORDER BY date DESC, id DESC"
                params = (user_id,)

            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [Expense.from_row(r) for r in rows]


class PostgresExpenseRepository(BaseExpenseRepository):
    """PostgreSQL / Supabase implementation using asyncpg."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._pool: Optional[Any] = None

    async def get_pool(self) -> Any:
        if asyncpg is None:
            raise RuntimeError("asyncpg is not installed. Please run: pip install asyncpg")
        if self._pool is None:
            dsn = self.dsn
            if dsn.startswith("postgres://"):
                dsn = dsn.replace("postgres://", "postgresql://", 1)
            self._pool = await asyncpg.create_pool(dsn, statement_cache_size=0)
        return self._pool

    async def init_db(self) -> None:
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS expenses (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    amount DOUBLE PRECISION NOT NULL,
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    date TEXT NOT NULL,
                    raw_message TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS budgets (
                    user_id BIGINT PRIMARY KEY,
                    monthly_budget DOUBLE PRECISION NOT NULL,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS category_budgets (
                    user_id BIGINT NOT NULL,
                    category TEXT NOT NULL,
                    amount DOUBLE PRECISION NOT NULL,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, category)
                );
                CREATE INDEX IF NOT EXISTS idx_expenses_user_date ON expenses (user_id, date);
                CREATE INDEX IF NOT EXISTS idx_expenses_created ON expenses (created_at);
                """
            )

    async def add_expense(
        self,
        user_id: int,
        amount: float,
        category: str,
        description: str,
        date: str,
        raw_message: Optional[str] = None,
    ) -> int:
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO expenses (user_id, amount, category, description, date, raw_message)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                user_id, float(amount), category, description, date, raw_message,
            )
            return row["id"] if row else 0

    async def add_expenses(
        self,
        user_id: int,
        items: List[Dict[str, Any]],
        raw_message: Optional[str] = None,
    ) -> List[int]:
        if not items:
            return []
        pool = await self.get_pool()
        inserted_ids = []
        async with pool.acquire() as conn:
            async with conn.transaction():
                for item in items:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO expenses (user_id, amount, category, description, date, raw_message)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        RETURNING id
                        """,
                        user_id, float(item["amount"]), item["category"], item["description"], item["date"], raw_message,
                    )
                    if row:
                        inserted_ids.append(row["id"])
        return inserted_ids

    async def get_expense_by_id(self, expense_id: int, user_id: int) -> Optional[Expense]:
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM expenses WHERE id = $1 AND user_id = $2",
                expense_id, user_id,
            )
            if row:
                return Expense(
                    id=row["id"],
                    user_id=row["user_id"],
                    amount=row["amount"],
                    category=row["category"],
                    description=row["description"],
                    date=row["date"],
                    raw_message=row["raw_message"],
                    created_at=str(row["created_at"]) if row["created_at"] else None,
                )
        return None

    async def delete_expense(self, expense_id: int, user_id: int) -> bool:
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM expenses WHERE id = $1 AND user_id = $2",
                expense_id, user_id,
            )
            return result.endswith("1")

    async def delete_expenses(self, expense_ids: List[int], user_id: int) -> int:
        if not expense_ids:
            return 0
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM expenses WHERE id = ANY($1::bigint[]) AND user_id = $2",
                expense_ids, user_id,
            )
            parts = result.split()
            return int(parts[1]) if len(parts) > 1 else 0

    async def get_expenses_by_date(self, user_id: int, date_str: str) -> List[Expense]:
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM expenses WHERE user_id = $1 AND date = $2 ORDER BY id ASC",
                user_id, date_str,
            )
            return [
                Expense(
                    id=row["id"],
                    user_id=row["user_id"],
                    amount=row["amount"],
                    category=row["category"],
                    description=row["description"],
                    date=row["date"],
                    raw_message=row["raw_message"],
                    created_at=str(row["created_at"]) if row["created_at"] else None,
                )
                for row in rows
            ]

    async def get_recent_expenses(self, user_id: int, limit: int = 10) -> List[Expense]:
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM expenses WHERE user_id = $1 ORDER BY id DESC LIMIT $2",
                user_id, limit,
            )
            return [
                Expense(
                    id=row["id"],
                    user_id=row["user_id"],
                    amount=row["amount"],
                    category=row["category"],
                    description=row["description"],
                    date=row["date"],
                    raw_message=row["raw_message"],
                    created_at=str(row["created_at"]) if row["created_at"] else None,
                )
                for row in rows
            ]

    async def get_daily_summary(self, user_id: int, date_str: str) -> Dict[str, Any]:
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            agg = await conn.fetchrow(
                "SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS count FROM expenses WHERE user_id = $1 AND date = $2",
                user_id, date_str,
            )
            total = float(agg["total"]) if agg else 0.0
            count = int(agg["count"]) if agg else 0

            categories = await conn.fetch(
                """
                SELECT category, SUM(amount) AS cat_total, COUNT(*) AS cat_count
                FROM expenses
                WHERE user_id = $1 AND date = $2
                GROUP BY category
                ORDER BY cat_total DESC
                """,
                user_id, date_str,
            )

        return {
            "date": date_str,
            "total": total,
            "count": count,
            "categories": [
                {
                    "category": row["category"],
                    "total": float(row["cat_total"]),
                    "count": int(row["cat_count"]),
                }
                for row in categories
            ],
        }

    async def get_monthly_summary(self, user_id: int, year: int, month: int) -> Dict[str, Any]:
        month_prefix = f"{year:04d}-{month:02d}-%"
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            agg = await conn.fetchrow(
                "SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS count FROM expenses WHERE user_id = $1 AND date LIKE $2",
                user_id, month_prefix,
            )
            total = float(agg["total"]) if agg else 0.0
            count = int(agg["count"]) if agg else 0

            categories = await conn.fetch(
                """
                SELECT category, SUM(amount) AS cat_total, COUNT(*) AS cat_count
                FROM expenses
                WHERE user_id = $1 AND date LIKE $2
                GROUP BY category
                ORDER BY cat_total DESC
                """,
                user_id, month_prefix,
            )

        return {
            "year": year,
            "month": month,
            "total": total,
            "count": count,
            "categories": [
                {
                    "category": row["category"],
                    "total": float(row["cat_total"]),
                    "count": int(row["cat_count"]),
                }
                for row in categories
            ],
        }

    async def set_budget(self, user_id: int, amount: float) -> None:
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO budgets (user_id, monthly_budget, updated_at)
                VALUES ($1, $2, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE
                SET monthly_budget = EXCLUDED.monthly_budget, updated_at = CURRENT_TIMESTAMP
                """,
                user_id, float(amount),
            )

    async def get_budget(self, user_id: int) -> Optional[float]:
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT monthly_budget FROM budgets WHERE user_id = $1", user_id
            )
            if row and float(row["monthly_budget"]) > 0:
                return float(row["monthly_budget"])
            sum_row = await conn.fetchrow(
                "SELECT SUM(amount) AS total FROM category_budgets WHERE user_id = $1",
                user_id,
            )
            if sum_row and sum_row["total"] is not None and float(sum_row["total"]) > 0:
                return float(sum_row["total"])
            return None

    async def set_category_budget(self, user_id: int, category: str, amount: float) -> None:
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            if amount <= 0:
                await conn.execute(
                    "DELETE FROM category_budgets WHERE user_id = $1 AND category = $2",
                    user_id, category,
                )
            else:
                await conn.execute(
                    """
                    INSERT INTO category_budgets (user_id, category, amount, updated_at)
                    VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
                    ON CONFLICT (user_id, category) DO UPDATE
                    SET amount = EXCLUDED.amount, updated_at = CURRENT_TIMESTAMP
                    """,
                    user_id, category, float(amount),
                )

    async def get_category_budgets(self, user_id: int) -> Dict[str, float]:
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT category, amount FROM category_budgets WHERE user_id = $1",
                user_id,
            )
            return {r["category"]: float(r["amount"]) for r in rows}

    async def get_category_budget(self, user_id: int, category: str) -> Optional[float]:
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT amount FROM category_budgets WHERE user_id = $1 AND category = $2",
                user_id, category,
            )
            return float(row["amount"]) if row else None

    async def clear_category_budgets(self, user_id: int) -> None:
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM category_budgets WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM budgets WHERE user_id = $1", user_id)

    async def get_all_expenses(
        self, user_id: int, year: Optional[int] = None, month: Optional[int] = None
    ) -> List[Expense]:
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            if year and month:
                prefix = f"{year:04d}-{month:02d}-%"
                rows = await conn.fetch(
                    "SELECT * FROM expenses WHERE user_id = $1 AND date LIKE $2 ORDER BY date DESC, id DESC",
                    user_id, prefix,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM expenses WHERE user_id = $1 ORDER BY date DESC, id DESC",
                    user_id,
                )
            return [
                Expense(
                    id=r["id"],
                    user_id=r["user_id"],
                    amount=float(r["amount"]),
                    category=r["category"],
                    description=r["description"],
                    date=str(r["date"]),
                    raw_message=r["raw_message"],
                    created_at=str(r["created_at"]) if r["created_at"] else None,
                )
                for r in rows
            ]


# Dynamic repository selection: uses PostgreSQL/Supabase if DATABASE_URL is set, else SQLite
if DATABASE_URL:
    repo: BaseExpenseRepository = PostgresExpenseRepository(DATABASE_URL)
else:
    repo: BaseExpenseRepository = SQLiteExpenseRepository(DATABASE_PATH)

