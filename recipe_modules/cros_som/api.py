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
    # A map from 'key' to `SomAnnotation`. Lazily loaded.
    self._key_to_annotation = {}

  def _get_key_to_annotation(self):
    """Return a map from 'key' to `SomAnnotation`, loading if needed."""
    if not self._key_to_annotation:
      token = self.m.service_account.default().get_access_token()
      response = self.m.url.get_json(
          self._annotations_url, transient_retry=3, log=True,
          step_name='get Sheriff-o-Matic annotations', headers={
              'Authorization': 'Bearer {}'.format(token)
          }, default_test_data=self.test_api.test_annotation_response)
      response.raise_on_error()

      for annotation in response.output:
        self._key_to_annotation[annotation['key']] = SomAnnotation(annotation)

    return self._key_to_annotation

  def get_annotation(self, step_name):
    """Return a `SomAnnotation` for `step_name`.

    None if there is no annotation for the step.
    """
    # Annotations for steps have keys like:
    # 'chromeos.buildbucket:results|hw test results|[FAILED] cave.hw.bvt-inline'
    key = KEY_PREFIX + step_name
    return self._get_key_to_annotation().get(key)
