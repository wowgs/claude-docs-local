"""A Claude Docs tab as data, with no network and no files (docsynclib does the calls):

- tree: the tab's XML as a tree;
- markdown: the tree as markdown plus chips, what a tab's local file holds;
- compare: two versions compared as the doc sees them;
- blocks: local markdown cut into blocks, list items and table rows;
- edits: the ops that turn a tab into a given markdown;
- write: what one write sends, and what the doc would not read back;
- inline: a paragraph as block content, for marks the doc's markdown does not read;
- fileview: a tab as its local file shows it (diagram pictures, links to tab files) and back;
- merge: a tab changed on both sides, merged block by block;
- errors: what this package reports instead of ending the program.
"""
