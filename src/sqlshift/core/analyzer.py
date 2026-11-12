from sqlglot import exp

from sqlshift.core.models import QueryComplexity


def analyze_query(tree: exp.Expression) -> tuple[bool, QueryComplexity, str]:
    """Анализирует AST-дерево запроса и определяет, является ли он аналитическим (OLAP).

    Returns:
        tuple[is_analytical, complexity, reason]
    """
    if isinstance(tree, (exp.Insert, exp.Update, exp.Delete)):
        return False, "low", f"Транзакционная операция (DML), ({tree.key.upper()})"

    if isinstance(
        tree,
        (
            exp.Create,
            exp.Drop,
            exp.TruncateTable,
            exp.Alter,
            exp.Transaction,
            exp.Commit,
            exp.Rollback,
            exp.Command,
            exp.Set,
        ),
    ):
        return False, "low", f"Команда управления DDL/TCL, ({tree.key.upper()})"

    if tree.find(exp.With):
        return True, "high", "Наличие CTE"

    if tree.find(exp.Group):
        return True, "high", "Наличие GROUP BY"

    if tree.find(exp.Window):
        return True, "high", "Наличие оконных функций"

    if tree.find(exp.Having):
        return True, "high", "Наличие HAVING"

    aggregations = list(tree.find_all(exp.AggFunc))
    if aggregations:
        agg_names = ", ".join({agg.key.upper() for agg in aggregations})
        return True, "medium", f"Наличие агрегатных функций: {agg_names}"

    joins = list(tree.find_all(exp.Join))
    if len(joins) >= 2:
        return True, "high", f"Множественное соединение ({len(joins)} JOIN)"
    elif len(joins) == 1:
        return False, "medium", "Одиночное соединение таблиц (OLTP JOIN)"

    return False, "low", "Обычный SELECT без сложных конструкций"
