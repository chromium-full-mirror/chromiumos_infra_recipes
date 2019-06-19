# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

from urlparse import urljoin

KEY_PREFIX = 'chromeos.buildbucket:'


class SomAnnotation(object):
  """Represents a single Sheriff-o-Matic annotation."""

  def __init__(self, annotation):
    """Initialize the annotation.

    Args:
      annotation (dict): A deserialized annotation returned from
        `ANNOTATIONS_URL`.
    """
    self._annotation = annotation

  @property
  def snooze_time_ms(self):
    """Returns the timestamp in milliseconds until which to snooze the alert.

    0 if there is no snooze on the alert.
    """
    return self._annotation['snoozeTime']

  @property
  def bugs(self):
    """Returns a list of bug ids linked to the bug.

    None if there are no linked bugs.
    """
    return self._annotation['bugs']


class CrosSomApi(recipe_api.RecipeApi):
  """A module for interacting with the ChromeOS Sheriff-o-Matic."""

  def __init__(self, properties, *args, **kwargs):
    super(CrosSomApi, self).__init__(*args, **kwargs)
    som_url = properties.som_url or 'https://sheriff-o-matic.appspot.com/chromeos'
    self._annotations_url = urljoin(som_url,
                                    '/api/v1/annotations/chromeos')
    # A map from step name to `SomAnnotation`. Lazily loaded.
    self._step_name_to_annotation = {}

  def _get_step_name_to_annotation(self):
    """Return a map from step name to `SomAnnotation`, loading if needed."""
    if not self._step_name_to_annotation:
      token = self.m.service_account.default().get_access_token()
      response = self.m.url.get_json(
          self._annotations_url, transient_retry=3, log=True,
          step_name='Get Sheriff-o-Matic annotations', headers={
              'Authorization': 'Bearer {}'.format(token)
          }, default_test_data=self.test_api.test_annotation_response)
      response.raise_on_error()

      for annotation in response.output:
        key = annotation['key']
        if not key.startswith(KEY_PREFIX):
          raise self.m.step.InfraFailure('Got unexpected key: {}'.format(key))

        self._step_name_to_annotation[key[len(KEY_PREFIX):]] = SomAnnotation(
            annotation)

    return self._step_name_to_annotation

  def get_annotation(self, step_name):
    """Return a `SomAnnotation` for `step_name`.

    None if there is no annotation for the step.
    """
    return self._get_step_name_to_annotation().get(step_name)
