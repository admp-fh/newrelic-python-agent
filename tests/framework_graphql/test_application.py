# Copyright 2010 New Relic, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import pytest
from testing_support.fixtures import validate_transaction_metrics, validate_transaction_errors, dt_enabled
from testing_support.validators.validate_span_events import validate_span_events

from newrelic.api.background_task import background_task
from newrelic.common.object_names import callable_name


@pytest.fixture(scope="session")
def is_graphql_2():
    from graphql import __version__ as version

    major_version = int(version.split(".")[0])
    return major_version == 2


@pytest.fixture(scope="session")
def graphql_run():
    try:
        from graphql import graphql_sync as graphql
    except ImportError:
        from graphql import graphql

    return graphql


def example_middleware(next, root, info, **args):
    return_value = next(root, info, **args)
    return return_value


def error_middleware(next, root, info, **args):
    raise RuntimeError("Runtime Error!")


_runtime_error_name = callable_name(RuntimeError)
_test_runtime_error = [(_runtime_error_name, "Runtime Error!")]
_expected_attributes = {
    "graphql.operation.name": "MyQuery",
    "graphql.operation.type": "query",
    "graphql.operation.deepestPath": "hello"
}
_graphql_base_rollup_metrics = [
    ("OtherTransaction/all", 1),
    ("GraphQL/all", 1),
    ("GraphQL/allOther", 1),
    ("GraphQL/GraphQL/all", 1),
    ("GraphQL/GraphQL/allOther", 1),
]


@dt_enabled
def test_basic(app, graphql_run, is_graphql_2):
    _test_basic_metrics = [
        ("OtherTransaction/Function/_target_application:resolve_hello", 1),
        ("GraphQL/operation/GraphQL/query/MyQuery/hello", 1),
        #("Function/_target_application:resolve_hello", 1),
    ]

    @validate_transaction_metrics(
        "_target_application:resolve_hello",
        rollup_metrics=_test_basic_metrics + _graphql_base_rollup_metrics,
        background_task=True,
    )
    @validate_span_events(exact_agents=_expected_attributes)
    @background_task()
    def _test():
        response = graphql_run(app, "query MyQuery{ hello }")
        assert not response.errors
        assert "Hello!" in str(response.data)

    _test()


def test_middleware(app, graphql_run, is_graphql_2):
    _test_middleware_metrics = [
        ("OtherTransaction/Function/_target_application:resolve_hello", 1),
        #("Function/_target_application:resolve_hello", 1),
        #("Function/test_application:example_middleware", "present"),  # 2?????
    ]

    @validate_transaction_metrics(
        "_target_application:resolve_hello",
        rollup_metrics=_test_middleware_metrics + _graphql_base_rollup_metrics,
        background_task=True,
    )
    @background_task()
    def _test():
        response = graphql_run(app, "{ hello }", middleware=[example_middleware])
        assert not response.errors
        assert "Hello!" in str(response.data)

    _test()


def test_exception_in_middleware(app, graphql_run):
    @validate_transaction_errors(errors=_test_runtime_error)
    @background_task()
    def _test():
        response = graphql_run(app, "{ hello }", middleware=[error_middleware])
        assert response.errors

    _test()


@pytest.mark.parametrize("field", ("error", "error_non_null"))
def test_exception_in_resolver(app, graphql_run, field):
    @validate_transaction_errors(errors=_test_runtime_error)
    @background_task()
    def _test():
        response = graphql_run(app, "{ %s }" % field)
        assert response.errors

    _test()


def test_exception_in_validation(app, graphql_run):
    from graphql.error import GraphQLError

    @validate_transaction_errors(errors=[callable_name(GraphQLError)])
    @background_task()
    def _test():
        response = graphql_run(app, "{ missing_field }")
        assert response.errors

    _test()


@pytest.mark.parametrize("query,operation_attrs", [("query MyQuery { library(index: 0) { name, book { name } } }", {})])
@dt_enabled
def test_operation_metrics_and_attrs(app, graphql_run, query, operation_attrs, is_graphql_2):    
    operation_metrics = [("GraphQL/operation/GraphQL/query/MyQuery/library.book.name", 1)]
    operation_attrs = {
        "graphql.operation.type": "query",
        "graphql.operation.name": "MyQuery",
        "graphql.operation.deepestPath": "library.book.name",
    }

    if is_graphql_2:
        txn_name = "graphql.execution.utils:default_resolve_fn"
    else:
        txn_name = "graphql.execution.execute:default_field_resolver"

    @validate_transaction_metrics(
        txn_name,
        scoped_metrics=operation_metrics,
        rollup_metrics=operation_metrics + _graphql_base_rollup_metrics,
        background_task=True,
    )
    @validate_span_events(exact_agents=operation_attrs)
    @background_task()
    def _test():
        response = graphql_run(app, query)
        assert not response.errors
    
    _test()


@dt_enabled
def test_field_resolver_metrics_and_attrs(app, graphql_run):
    field_resolver_metrics = [("GraphQL/resolve/GraphQL/hello", 1)]
    graphql_attrs = {
        "graphql.field.name": "hello",
        "graphql.field.parentType": "Query",
        "graphql.field.path": "hello",
    }

    @validate_transaction_metrics(
        "_target_application:resolve_hello",
        scoped_metrics=field_resolver_metrics,
        rollup_metrics=field_resolver_metrics + _graphql_base_rollup_metrics,
        background_task=True,
    )
    @validate_span_events(exact_agents=graphql_attrs)
    @background_task()
    def _test():
        response = graphql_run(app, "{ hello }")
        assert not response.errors
        assert "Hello!" in str(response.data)

    _test()