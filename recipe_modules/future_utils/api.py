# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from collections import namedtuple

import gevent

from recipe_engine import recipe_api

CallResponse = namedtuple('CallResponse',
                          ['req', 'resp', 'call_count', 'errored'])


class FutureUtilsApi(recipe_api.RecipeApi):
  """A module to run things in parallel.

  This module is intended to be used by any task that should run async. It
  supports maximum concurrency, and also waits for responses if asked to.

  The biggest draw of using this module is the pairing of request object to
  response object. As such, it differs from the futures interface by requiring
  request be a single object. This object could easily be a dict for multiple
  inputs if needed.

  Usage:
  ```
  runner = api.future_utils.create_parallel_runner(2)
  # First function.
  runner.run_function_async(
    lambda req, _: "response 1",
    "request 1",
  )
  # Second function (in parallel).
  runner.run_function_async(
    lambda req, _: "response 2",
    "request 2",
  )
  # Third function (will run after one of the first two completes).
  runner.run_function_async(
    lambda req, _: "response 3",
    "request 3",
  )
  # Get responses.
  responses = runner.wait_for_and_get_responses()
  assert responses == [
    CallResponse('request 1', 'response 1', 1),
    CallResponse('request 2', 'response 2', 1),
    CallResponse('request 3', 'response 3', 1),
  ]
  ```

  For more options, read the docs of ParallelRunner below.
  """

  def create_parallel_runner(self, max_concurrent_requests=None):
    """Create a parallel runner, bounded to the provided number of concurrency.

    Args:
      max_concurrent_requests: max number of requests to run in parallel.
        Defaults to None, which means unlimited.

    Returns:
      A ParallelRunner that can be used to kick off async jobs, and wait for
        them to resolve.
    """
    # Recipes engine has a wrapper for BoundedSemaphore but not for
    # DummySemaphore. In order to maintain the same contract, pass through an
    # unbounded semaphore if there is no concurrency limit.
    semaphore = self.m.futures.make_bounded_semaphore(
        max_concurrent_requests
    ) if max_concurrent_requests else gevent.lock.DummySemaphore()
    return ParallelRunner(semaphore, self.m.futures)

  @staticmethod
  def create_custom_response(req, resp, call_count, errored=False):
    """Create a custom CallResponse, for convenience in logic.

    Args:
      req: request object to include.
      resp: response object to include.
      call_count: number of calls.
      errored: whether the call errored or not.

    Returns:
      A custom CallResponse for the given properties.
    """
    return CallResponse(req, resp, call_count, errored)


class ParallelRunner():
  """Parallel runner class.

  This class encapsulates all the parallel runs that should be grouped together.

  To support running many jobs in parallel that are unrelated, a caller can
  simply create a new ParallelRunner for a new task type, and they will use
  different semaphores to guarantee `max_concurrent_requests`.
  """

  def __init__(self, semaphore, futures):
    self._futures = []
    self._semaphore = semaphore
    # Holder to futures module so it can be used in a class not part of the
    # recipes engine dependency injection ecosystem.
    self._futures_module = futures

  def run_function_async(self, func, req, success_handler=lambda *args: None,
                         error_handler=lambda *args: None, try_count=1):
    """Run the provided function in a new thread.

    Args:
      func (Callable[[Any, int], resp]): the function to run in parallel. The
        function takes in the req object (below) and number attempt.
      req (Any): the request object to pass in to the function.
      success_handler (Callable[Any]): a function to run upon function success.
        Should accept the response object type.
      error_handler (Callable[Error]): a function to run upon function failure.
        If try_count is greater than 1, this will be executed on every failure.
      try_count (int): number of attempts to make before returning an exception.
        Defaults to 1.
    """

    def wrap_call_in_retries():
      num_tries = 0
      last_err = None
      while num_tries < try_count:
        try:
          with self._semaphore:
            num_tries += 1
            resp = func(req, num_tries)
            success_handler(resp)

            return CallResponse(req, resp, num_tries, False)
        except Exception as e:  # pylint: disable=broad-except
          last_err = e
          error_handler(e)
      return CallResponse(req, last_err, num_tries, True)

    self._futures.append(self._futures_module.spawn(wrap_call_in_retries))

  def wait_for_and_get_responses(self):
    """Wait for all futures to resolve and return their results.

    Returns:
      An array of CallResponses when all calls complete.
    """
    results = []
    for f in self._futures_module.iwait(self._futures):
      results.append(f.result())
    return results

  def wait_for_and_throw(self):
    """Wait for all futures to resolve and throw any exceptions."""
    for f in self._futures_module.iwait(self._futures):
      if f.result().errored:
        raise f.result().resp
