from posapp.models import Expense


class ExpenseTransitionConverter:
    actions = Expense.list_actions()
    regex = f'(?:{"|".join(actions)})'

    def to_python(self, value):
        if value in self.actions:
            return str(value)
        else:
            raise ValueError("value must be one of " + str(self.actions))

    def to_url(self, value):
        if value in self.actions:
            return str(value)
        else:
            raise ValueError("value must be one of " + str(self.actions))
