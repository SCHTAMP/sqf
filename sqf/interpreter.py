from sqf.types import Statement, Code, Number, Boolean, Nothing, Variable, Array, String, Type, File
from sqf.interpreter_types import PrivateType
from sqf.keywords import Keyword
from sqf.parser import parse
from sqf.exceptions import ExecutionError, SQFParserError
from sqf.interpreter_expressions import EXPRESSIONS
from sqf.base_interpreter import BaseInterpreter


class Interpreter(BaseInterpreter):

    def __init__(self, all_vars=None):
        super().__init__(all_vars)

        self._simulation = None
        self._client = None

    @property
    def simulation(self):
        if self._simulation is None:
            raise ExecutionError('Trying to access simulation without a simulation assigned')
        return self._simulation

    @property
    def client(self):
        if self._client is None:
            raise ExecutionError('Trying to access client without a client')
        return self._client

    @client.setter
    def client(self, client):
        self._client = client
        self._simulation = client.simulation

    def execute_token(self, token):
        """
        Given a single token, recursively evaluate it and return its value.
        """
        # interpret the statement recursively
        if isinstance(token, Statement):
            result = self.execute_single(statement=token)
        elif isinstance(token, Array):
            # empty statements are ignored
            result = Array([self.execute_token(s)[1] for s in token.value if s])
        elif token == Keyword('isServer'):
            result = Boolean(self.client.is_server)
        elif token == Keyword('isClient'):
            result = Boolean(self.client.is_client)
        elif token == Keyword('isDedicated'):
            result = Boolean(self.client.is_dedicated)
        else:
            result = token

        result.position = token.position
        return result, self.value(result)

    def execute_single(self, statement):
        assert(not isinstance(statement, Code))

        outcome = Nothing()
        _outcome = outcome
        if not statement.base_tokens:
            return outcome

        # evaluate the types of all tokens
        base_tokens = statement.base_tokens
        values = []
        tokens = []
        types = []

        for token in base_tokens:
            t, v = self.execute_token(token)
            values.append(v)
            tokens.append(t)
            types.append(type(v))

        case_found = None
        for case in EXPRESSIONS:
            if case.is_match(values):
                case_found = case
                break

        if case_found is not None:
            outcome = case_found.execute(values, self)
        # todo: replace all elif below by expressions
        elif len(tokens) == 2 and tokens[0] == Keyword('publicVariable'):
            if not isinstance(tokens[1], String) or tokens[1].value.startswith('_'):
                raise SQFParserError(statement.position, 'Interpretation of "%s" failed' % statement)

            var_name = tokens[1].value
            scope = self.get_scope(var_name, 'missionNamespace')
            self.simulation.broadcast(var_name, scope[var_name])

        elif len(tokens) == 2 and tokens[0] == Keyword('publicVariableServer'):
            if not isinstance(tokens[1], String) or tokens[1].value.startswith('_'):
                raise SQFParserError(statement.position, 'Interpretation of "%s" failed' % statement)

            var_name = tokens[1].value
            scope = self.get_scope(var_name, 'missionNamespace')
            self.simulation.broadcast(var_name, scope[var_name], -1)  # -1 => to server

        elif len(tokens) == 2 and tokens[0] == Keyword('private'):
            if isinstance(values[1], String):
                self.add_privates([values[1]])
            elif isinstance(values[1], Array):
                self.add_privates(values[1].value)
            elif isinstance(base_tokens[1], Statement) and isinstance(base_tokens[1].base_tokens[0], Variable):
                var = base_tokens[1].base_tokens[0]
                self.add_privates([String('"' + var.name + '"')])
                outcome = PrivateType(var)
        # binary operators
        elif len(tokens) == 3 and tokens[1] in (Keyword('='), Keyword('publicVariableClient')):
            # it is a binary statement: token, operation, token
            lhs = tokens[0]
            lhs_v = values[0]
            lhs_t = types[0]

            op = tokens[1]
            rhs = tokens[2]
            rhs_v = values[2]
            rhs_t = types[2]

            if op == Keyword('='):
                if isinstance(lhs, PrivateType):
                    lhs = lhs.variable
                else:
                    lhs = self.get_variable(base_tokens[0])

                if not isinstance(lhs, Variable) or not isinstance(rhs_v, Type):
                    raise SQFParserError(statement.position, 'Interpretation of "%s" failed' % statement)

                scope = self.get_scope(lhs.name)
                scope[lhs.name] = rhs_v
                outcome = rhs
            elif op == Keyword('publicVariableClient'):
                if not lhs_t == Number or rhs.value.startswith('_'):
                    raise SQFParserError(statement.position, 'Interpretation of "%s" failed' % statement)
                client_id = lhs.value
                var_name = rhs.value
                scope = self.get_scope(var_name, 'missionNamespace')
                self.simulation.broadcast(var_name, scope[var_name], client_id)
        # code, variables and values
        elif len(tokens) == 1 and isinstance(tokens[0], (Type, Keyword)):
            outcome = values[0]
        else:
            raise SQFParserError(statement.position, 'Interpretation of "%s" failed')

        if statement.ending:
            outcome = _outcome
        return outcome


def interpret(script, interpreter=None):
    if interpreter is None:
        interpreter = Interpreter()
    assert(isinstance(interpreter, Interpreter))

    statements = parse(script)

    file = File(statements._tokens)
    file.set_position((1, 1))

    outcome = interpreter.execute_code(file, extra_scope={'_this': Nothing()})

    return interpreter, outcome
