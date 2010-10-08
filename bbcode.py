#!/usr/bin/env python

import re

# Taken from http://daringfireball.net/2010/07/improved_regex_for_matching_urls
_url_re = re.compile( r'(?i)\b((?:[a-z][\w-]+:(?:/{1,3}|[a-z0-9%])|www\d{0,3}[.]|[a-z0-9.\-]+[.][a-z]{2,4}/)(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|[^\s`!()\[\]{};:\'".,<>?]))', re.MULTILINE )

class TagOptions (object):
	
	tag_name = None
	newline_closes = False
	standalone = False
	render_embedded = True
	transform_newlines = True
	escape_html = True
	replace_links = True
	replace_cosmetic = True
	
	def __init__( self, tag_name, **kwargs ):
		self.tag_name = tag_name
		for attr, value in kwargs.items():
			setattr( self, attr, bool(value) )

class Parser (object):
	
	TOKEN_TAG_START = 1
	TOKEN_TAG_END = 2
	TOKEN_NEWLINE = 3
	TOKEN_DATA = 4
	
	REPLACE_ESCAPE = (
		('&', '&amp;'),
		('<', '&lt;'),
		('>', '&gt;'),
	)
	
	REPLACE_COSMETIC = (
		('---', '&mdash;'),
		('--', '&ndash;'),
		('...', '&#8230;'),
		('(c)', '&copy;'),
		('(reg)', '&reg;'),
		('(tm)', '&trade;'),
	)
	
	def __init__( self, newline='<br />', normalize_newlines=True, install_defaults=True, escape_html=True, \
					replace_links=True, replace_cosmetic=True, tag_opener='[', tag_closer=']' ):
		self.tag_opener = tag_opener
		self.tag_closer = tag_closer
		self.newline = newline
		self.normalize_newlines = normalize_newlines
		self.recognized_tags = {}
		self.escape_html = escape_html
		self.replace_cosmetic = replace_cosmetic
		self.replace_links = replace_links
		if install_defaults:
			self.install_default_formatters()
	
	def add_formatter( self, tag_name, render_func, **kwargs ):
		"""
		Installs a render function for the specified tag name. The render function
		should have the following signature:
		
			def render( value, options, context, parent ):
				...
		
		The arguments are as follows:
			
			value
				The context between start and end tags, or None for standalone tags.
				Whether this has been rendered depends on render_embedded tag option.
			options
				A dictionary of options specified on the opening tag, or None.
			context
				The user-defined context value passed into the format call.
			parent
				The parent TagOptions, if the tag is being rendered inside another tag,
				otherwise None.
		"""
		options = TagOptions( tag_name.strip().lower(), **kwargs )
		self.recognized_tags[options.tag_name] = (render_func, options)
	
	def add_simple_formatter( self, tag_name, format, **kwargs ):
		def _render( value, options, context, parent ):
			fmt = {}
			if options:
				fmt.update( options )
			fmt.update( {'value': value} )
			return format % fmt
		self.add_formatter( tag_name, _render, **kwargs )
	
	def install_default_formatters( self ):
		self.add_simple_formatter( 'b', '<strong>%(value)s</strong>' )
		self.add_simple_formatter( 'i', '<em>%(value)s</em>' )
		self.add_simple_formatter( 'list', '<ul>%(value)s</ul>', transform_newlines=False )
		self.add_simple_formatter( '*', '<li>%(value)s</li>', newline_closes=True )
		self.add_simple_formatter( 'url', '<a href="%(value)s">%(value)s</a>', replace_links=False, replace_cosmetic=False )
		self.add_simple_formatter( 'quote', '<blockquote>%(value)s</blockquote>' )
	
	def _replace( self, data, replacements ):
		"""
		Given a list of 2-tuples (find, repl) this function performs all
		replacements on the input and returns the result.
		"""
		for find, repl in replacements:
			data = data.replace( find, repl )
		return data
	
	def _newline_tokenize( self, data ):
		"""
		Given a string that does not contain any tags, this function will
		return a list of NEWLINE and DATA tokens such that if you concatenate
		their data, you will have the original string.
		"""
		parts = data.split( '\n' )
		tokens = []
		for num, part in enumerate(parts):
			if part:
				tokens.append( (self.TOKEN_DATA, None, None, part) )
			if num < (len(parts) - 1):
				tokens.append( (self.TOKEN_NEWLINE, None, None, '\n') )
		return tokens
	
	def _parse_opts( self, data ):
		"""
		Given a tag string, this function will parse any options out of it and
		return a tuple of (tag_name, options_dict). Options may be quoted in order
		to preserve spaces, and free-standing options are allowed. The tag name
		itself may also serve as an option if it is immediately followed by an equal
		sign. Here are some examples:
			quote author="Dan Watson"
				tag_name=quote, options={'author': 'Dan Watson'}
			url="http://test.com/s.php?a=bcd efg" popup
				tag_name=url, options={'url': 'http://test.com/s.php?a=bcd efg', 'popup': ''}
		"""
		name = None
		opts = {}
		in_value = False
		in_quote = False
		attr = ''
		value = ''
		for pos, ch in enumerate(data):
			if in_value:
				if in_quote:
					if ch == '"':
						in_quote = False
					else:
						value += ch
				else:
					if ch == '"':
						in_quote = True
					elif ch == ' ':
						opts[attr] = value
						attr = ''
						value = ''
						in_value = False
					else:
						value += ch
			else:
				if ch == '=':
					in_value = True
					if name is None:
						name = attr
				elif ch == ' ':
					if name is None:
						name = attr
					elif attr:
						opts[attr] = ''
					attr = ''
				else:
					attr += ch
			if attr and pos == len(data) - 1:
				opts[attr] = value
		return name, opts
	
	def _parse_tag( self, tag ):
		"""
		Given a tag string (characters enclosed by []), this function will
		parse any options and return a tuple of the form:
			(valid, tag_name, closer, options)
		"""
		if (not tag.startswith(self.tag_opener)) or (not tag.endswith(self.tag_closer)) or ('\n' in tag) or ('\r' in tag):
			return (False, tag, False, None)
		# TODO: should [b] == [ b ]?
		tag_name = tag[len(self.tag_opener):-len(self.tag_closer)].strip()
		if not tag_name:
			return (False, tag, False, None)
		closer = False
		opts = None
		if tag_name[0] == '/':
			tag_name = tag_name[1:]
			closer = True
		# Parse options inside the opening tag, if needed.
		if (('=' in tag_name) or (' ' in tag_name)) and not closer:
			tag_name, opts = self._parse_opts( tag_name )
		return (True, tag_name.strip().lower(), closer, opts)
	
	def tokenize( self, data ):
		"""
		Tokenizes the given string. A token is a 4-tuple of the form:
			(token_type, tag_name, tag_options, token_text)
		
		token_type
			One of: TOKEN_TAG_START, TOKEN_TAG_END, TOKEN_NEWLINE, TOKEN_DATA
		tag_name
			The name of the tag if token_type=TOKEN_TAG_*, otherwise None
		tag_options
			A dictionary of options specified for TOKEN_TAG_START, otherwise None
		token_text
			The original token text
		"""
		if self.normalize_newlines:
			data = data.replace( '\r\n', '\n' ).replace( '\r', '\n' )
		pos = start = end = 0
		tokens = []
		while pos < len(data):
			start = data.find( self.tag_opener, pos )
			if start >= pos:
				# Check to see if there was data between this start and the last end.
				if start > pos:
					tl = self._newline_tokenize( data[pos:start] )
					tokens.extend( tl )
				end = data.find( self.tag_closer, start )
				# Check to see if another tag opens before this one closes.
				new_check = data.find( self.tag_opener, start+len(self.tag_opener) )
				if new_check > 0 and new_check < end:
					tokens.extend( self._newline_tokenize(data[start:new_check]) )
					pos = new_check
				elif end > start:
					tag = data[start:end+len(self.tag_closer)]
					valid, tag_name, closer, opts = self._parse_tag( tag )
					# Make sure this is a well-formed, recognized tag, otherwise it's just data.
					if valid and tag_name in self.recognized_tags:
						if closer:
							tokens.append( (self.TOKEN_TAG_END, tag_name, None, tag) )
						else:
							tokens.append( (self.TOKEN_TAG_START, tag_name, opts, tag) )
					else:
						tokens.extend( self._newline_tokenize(tag) )
					pos = end + len(self.tag_closer)
				else:
					# An unmatched [
					break
			else:
				# No more tags left to parse.
				break
		if pos < len(data):
			tl = self._newline_tokenize( data[pos:] )
			tokens.extend( tl )
		return tokens
	
	def _find_closing_token( self, tag, tokens, pos ):
		"""
		Given the current tag options, a list of tokens, and the current position
		in the token list, this function will find the position of the closing token
		associated with the specified tag. This may be a closing tag, a newline, or
		simply the end of the list (to ensure tags are closed).
		"""
		embed_count = 0
		while pos < len(tokens):
			token_type, tag_name, tag_opts, token_text = tokens[pos]
			if token_type == self.TOKEN_NEWLINE and tag.newline_closes:
				# If for some crazy reason there are embedded tags that both close on newline,
				# the first newline will automatically close all those nested tags.
				return pos
			elif token_type == self.TOKEN_TAG_START and tag_name == tag.tag_name:
				embed_count += 1
			elif token_type == self.TOKEN_TAG_END and tag_name == tag.tag_name:
				if embed_count > 0:
					embed_count -= 1
				else:
					return pos
			pos += 1
		return pos
	
	def _transform( self, data, escape_html, replace_links, replace_cosmetic ):
		"""
		Transforms the input string based on the options specified, taking into account
		whether the option is enabled globally for this parser.
		"""
		if self.escape_html and escape_html:
			data = self._replace( data, self.REPLACE_ESCAPE )
		if self.replace_cosmetic and replace_cosmetic:
			data = self._replace( data, self.REPLACE_COSMETIC )
		if self.replace_links and replace_links:
			data = _url_re.sub( r'<a href="\1">\1</a>', data )
		return data
	
	def _format_tokens( self, tokens, context, parent=None ):
		idx = 0
		formatted = u''
		while idx < len(tokens):
			token_type, tag_name, tag_opts, token_text = tokens[idx]
			if token_type == self.TOKEN_TAG_START:
				render_func, tag = self.recognized_tags[tag_name]
				if tag.standalone:
					formatted += render_func( None, tag_opts, context, parent )
				else:
					# First, find the extent of this tag's tokens.
					end = self._find_closing_token( tag, tokens, idx+1 )
					subtokens = tokens[idx+1:end]
					if tag.render_embedded:
						# This tag renders embedded tags, simply recurse.
						inner = self._format_tokens( subtokens, context, parent=tag )
					else:
						# Otherwise, just concatenate all the token text.
						inner = self._transform( u''.join([t[3] for t in subtokens]), tag.escape_html, tag.replace_links, tag.replace_cosmetic )
						if tag.transform_newlines:
							inner = inner.replace( '\n', self.newline )
					formatted += render_func( inner, tag_opts, context, parent )
					# Skip to the end tag.
					idx = end
			elif token_type == self.TOKEN_NEWLINE:
				formatted += self.newline if (parent is None or parent.transform_newlines) else token_text
			elif token_type == self.TOKEN_DATA:
				escape = self.escape_html if parent is None else parent.escape_html
				links = self.replace_links if parent is None else parent.replace_links
				cosmetic = self.replace_cosmetic if parent is None else parent.replace_cosmetic
				formatted += self._transform( token_text, escape, links, cosmetic )
			idx += 1
		return formatted
	
	def format( self, data, context=None ):
		tokens = self.tokenize( data )
		return self._format_tokens( tokens, context )
	
	def strip( self, data, strip_newlines=False ):
		text = []
		for token_type, tag_name, tag_opts, token_text in self.tokenize( data ):
			if token_type == self.TOKEN_DATA:
				text.append( token_text )
			elif token_type == self.TOKEN_NEWLINE and not strip_newlines:
				text.append( token_text )
		return u''.join( text )

g_parser = None

def render_html( input, context=None ):
	"""
	A module-level convenience method that creates a default bbcode parser,
	and renders the input string as HTML.
	"""
	global g_parser
	if g_parser is None:
		g_parser = Parser()
	return g_parser.format( input, context )

if __name__ == '__main__':
	import sys
	print render_html( sys.stdin.read() )
