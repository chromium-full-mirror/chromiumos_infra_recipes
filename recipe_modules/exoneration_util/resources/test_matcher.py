# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Local unit test for matcher module."""
import unittest

from google.protobuf import json_format
from PB.go.chromium.org.luci.resultdb.proto.v1.resultdb import \
  QueryTestVariantsResponse

from ..matcher import TestVariantMatcher  # pylint: disable=relative-beyond-top-level

file_path_single_source = './exoneration_util/resources/test_data.json'
file_path_multiple_sources = './exoneration_util/resources/test_data_multiple_sources.json'


class TestMatcher(unittest.TestCase):
  """Simple test cases for verifying basic logic and debugging locally. Actual
  test coverage is in recipes tests."""

  def test_match_single_source(self):

    def query_func(page_token=None):  # pylint: disable=unused-argument
      return self.load_data(file_path_single_source)

    test_variants = self.get_variants()
    matcher = TestVariantMatcher(query_func)
    result = matcher.match_sources(test_variants)
    self.assertEqual(len(result), 2)
    self.assertEqual(result[0]['sources']['gitilesCommit']['commitHash'],
                     '93cf925c8cd052ebbe6133a8cef885d92c56cdc5')
    self.assertEqual(result[1]['sources']['gitilesCommit']['commitHash'],
                     '93cf925c8cd052ebbe6133a8cef885d92c56cdc5')

  def test_match_multiple_sources(self):

    def query_func(page_token=None):  # pylint: disable=unused-argument
      return self.load_data(file_path_multiple_sources)

    test_variants = self.get_variants()
    matcher = TestVariantMatcher(query_func)
    result = matcher.match_sources(test_variants)
    self.assertEqual(len(result), 2)
    self.assertEqual(result[0]['sources']['gitilesCommit']['commitHash'],
                     'aaaa')
    self.assertEqual(result[1]['sources']['gitilesCommit']['commitHash'],
                     'bbbb')

  def test_match_multiple_sources_multi_key_variant(self):

    def query_func(page_token=None):  # pylint: disable=unused-argument
      return self.load_data(file_path_multiple_sources)

    test_variants = self.get_variants_multi_key()
    matcher = TestVariantMatcher(query_func)
    result = matcher.match_sources(test_variants)
    self.assertEqual(len(result), 2)
    self.assertEqual(result[0]['sources']['gitilesCommit']['commitHash'],
                     'aaaa')
    self.assertEqual(result[1]['sources']['gitilesCommit']['commitHash'],
                     'bbbb')

  def test_match_paging(self):

    def query_func(page_token=None):
      if page_token:
        return self.load_data(file_path_single_source)

      data = self.load_data(file_path_multiple_sources)
      data.next_page_token = '1'
      return data

    test_variants = self.get_variants()
    matcher = TestVariantMatcher(query_func)
    result = matcher.match_sources(test_variants)
    self.assertEqual(len(result), 2)
    self.assertEqual(result[0]['sources']['gitilesCommit']['commitHash'],
                     '93cf925c8cd052ebbe6133a8cef885d92c56cdc5')
    self.assertEqual(result[1]['sources']['gitilesCommit']['commitHash'],
                     '93cf925c8cd052ebbe6133a8cef885d92c56cdc5')

  def read_file(self, file_path: str) -> str:
    with open(file_path, mode='r',
              encoding='utf-8') as file:  # 'r' mode for reading
      content = file.read()
    return content

  def load_data(self, file_path) -> QueryTestVariantsResponse:
    content = self.read_file(file_path)
    return json_format.Parse(text=content, message=QueryTestVariantsResponse(),
                             ignore_unknown_fields=True)

  def get_variants(self):
    return [{
        'testId': 'tast.hwsec.Login',
        'variant': {
            'def': {
                'build_target': 'amd64-generic'
            }
        }
    }, {
        'testId': 'tast.session.OwnershipTaken',
        'variant': {
            'def': {
                'build_target': 'amd64-generic'
            }
        }
    }]

  def get_variants_multi_key(self):
    """Multiple keys in def map and order is switched from json."""
    return [{
        'testId': 'tast.hwsec.Login',
        'variant': {
            'def': {
                'model': 'dedede',
                'build_target': 'dedede'
            }
        }
    }, {
        'testId': 'tast.session.OwnershipTaken',
        'variant': {
            'def': {
                'board': 'betty'
            }
        }
    }]
