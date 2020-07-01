from typing import Type

from posapp.models import HasActionsMixin, Expense, Member


def generate_transition_converter(cls: Type[HasActionsMixin], group: str = "state"):
    class TransitionConverter:
        actions = cls.list_actions(group)
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

    return TransitionConverter


ExpenseTransitionConverter = generate_transition_converter(Expense)
MembershipTransitionConverter = generate_transition_converter(Member, "membership_status")
