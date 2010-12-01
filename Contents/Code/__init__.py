import datetime, re, time, unicodedata, hashlib

# [might want to look into language/country stuff at some point] 
# param info here: http://code.google.com/apis/ajaxsearch/documentation/reference.html
#
GOOGLE_JSON_URL = 'http://ajax.googleapis.com/ajax/services/search/web?v=1.0&userip=%s&rsz=large&q=%s'
FREEBASE_URL    = 'http://freebase.plexapp.com'

def Start():
  HTTP.CacheTime = CACHE_1HOUR * 4
  
class PlexMovieAgent(Agent.Movies):
  name = 'Freebase'
  languages = [Locale.Language.English, Locale.Language.Swedish, Locale.Language.French, 
               Locale.Language.Spanish, Locale.Language.Dutch, Locale.Language.German, 
               Locale.Language.Italian]

  def identifierize(self, string):
      string = re.sub( r"\s+", " ", string.strip())
      string = unicodedata.normalize('NFKD', unicode(string))
      string = re.sub(r"['\"!?@#$&%^*\(\)_+\.,;:/]","", string)
      string = re.sub(r"[_ ]+","_", string)
      string = string.strip('_')
      return string.strip().lower()

  def guidize(self, string):
    hash = hashlib.sha1()
    hash.update(string.encode('utf-8'))
    return hash.hexdigest()

  def titleyear_guid(self, title, year):
    if year == '' or year is None or not year:
      string = "%s" % self.identifierize(title)
    else:
      string = "%s_%s" % (self.identifierize(title).lower(), year)
    return self.guidize("%s" % string)
  
  def getPublicIP(self):
    ip = HTTP.Request('http://plexapp.com/ip.php').content.strip()
    return ip
  
  def getGoogleResults(self, url):
    try:
      jsonObj = JSON.ObjectFromURL(url, sleep=0.5)
      if jsonObj['responseData'] != None:
        jsonObj = jsonObj['responseData']['results']
        if len(jsonObj) > 0:
          return jsonObj
    except:
      Log("Exception obtaining result from Google.")
    
    return []
  
  def search(self, results, media, lang):
    
    # Keep track of best name.
    idMap = {}
    bestNameMap = {}
    bestNameDist = 1000
    
    # See if we're being passed a raw ID.
    if media.guid or re.match('t*[0-9]{7}', media.name):
      theGuid = media.guid or media.name
      if not theGuid.startswith('tt'):
        theGuid = 'tt' + theGuid
      
      # Add a result for the id found in the passed in guid hint.
      (title, year) = self.findById(theGuid)
      if title is not None:
        results.Append(MetadataSearchResult(id=theGuid, name=title, year=year, lang=lang, score=100))
        bestNameMap[theGuid] = title
          
    if media.year:
      searchYear = ' (' + str(media.year) + ')'
    else:
      searchYear = ''

    # first look in the proxy/cache 
    titleyear_guid = self.titleyear_guid(media.name,searchYear)

    # title|year search vector
    url = '%s/movie/guid/%s/%s.xml' % (FREEBASE_URL, titleyear_guid[0:2], titleyear_guid)
    Log("checking title|year search vector: %s" % url)
    try:
      res = XML.ElementFromURL(url)
      for match in res.xpath('//match'):
        id       = "tt%s" % match.get('guid')
        if idMap.has_key(id):
          continue
        imdbName = match.get('title')
        imdbYear = match.get('year')
        score    = match.get('percentage')
        idMap[id] = True
        bestNameMap[id] = imdbName 
        results.Append(MetadataSearchResult(id = id, name  = imdbName, year = imdbYear, lang  = lang, score = score))
    except:
      Log("freebase/proxy guid lookup failed")

    # plexhash search vector
#    url = '%s/movie/hash/%s/%s.xml' % (FREEBASE_URL, media.name[0:2], media.name)
#    Log("checking plexhash search vector: %s" % url)
#    try:
#      res = XML.ElementFromURL(url)
#      for match in res.xpath('//match'):
#        id       = "tt%s" % match.get('guid')
#        if idMap.has_key(id):
#          continue
#        imdbName = match.get('title')
#        imdbYear = match.get('year')
#        score    = match.get('percentage')
#        idMap[id] = True
#        bestNameMap[id] = imdbName 
#        results.Append(MetadataSearchResult(id = id, name  = imdbName, year = imdbYear, lang  = lang, score = score))
#    except:
#      Log("freebase/proxy guid lookup failed")

    if len(results) == 0:
    
      normalizedname = string.stripdiacritics(media.name)
      google_json_quotes = google_json_url % (self.getpublicip(), string.quote('"' + normalizedname + searchyear + '"', useplus=true)) + '+site:imdb.com'
      google_json_noquotes = google_json_url % (self.getpublicip(), string.quote(normalizedname + searchyear, useplus=true)) + '+site:imdb.com'
      google_json_nosite = google_json_url % (self.getpublicip(), string.quote(normalizedname + searchyear, useplus=true)) + '+imdb.com'
      
      subsequentsearchpenalty = 0
      
      for s in [google_json_quotes, google_json_noquotes]:
        if s == google_json_quotes and (media.name.count(' ') == 0 or media.name.count('&') > 0 or media.name.count(' and ') > 0):
          # no reason to run this test, plus it screwed up some searches
          continue 
          
        subsequentsearchpenalty += 1
  
        # check to see if we need to bother running the subsequent searches
        log("we have %d results" % len(results))
        if len(results) < 3:
          score = 99
          
          # make sure we have results and normalize them.
          jsonobj = self.getgoogleresults(s)
            
          # now walk through the results.    
          for r in jsonobj:
            
            # get data.
            url = r['unescapedurl']
            title = r['titlenoformatting']
            
            # parse the name and year.
            imdbname, imdbyear = self.parsetitle(title)
            if not imdbname:
              # doesn't match, let's skip it.
              log("skipping strange title: " + title + " with url " + url)
              continue
            else:
              log("using [%s] derived from [%s] (url=%s)" % (imdbname, title, url))
              
            scorepenalty = 0
            url = r['unescapedurl'].lower().replace('us.vdc','www').replace('title?','title/tt') #massage some of the weird url's google has
            if url[-1:] == '/':
              url = url[:-1]
      
            spliturl = url.split('/')
      
            if len(spliturl) == 6 and re.match('tt[0-9]+', spliturl[-2]) is not none:
              
              # this is the case where it is not just a link to the main imdb title page, but to a subpage. 
              # in some odd cases, google is a bit off so let's include these with lower scores "just in case".
              #
              scorepenalty = 10
              del spliturl[-1]
      
            if len(spliturl) > 5 and re.match('tt[0-9]+', spliturl[-1]) is not none:
              while len(spliturl) > 5:
                del spliturl[-2]
              scorepenalty += 5
  
            if len(spliturl) == 5 and re.match('tt[0-9]+', spliturl[-1]) is not none:
              
              id = spliturl[-1]
              if id.count('+') > 0:
                # penalizing for abnormal tt link.
                scorepenalty += 10
              try:
                
                # keep the closest name around.
                distance = util.levenshteindistance(media.name, imdbname)
                if not bestnamemap.has_key(id) or distance < bestnamedist:
                  bestnamemap[id] = imdbname
                  bestnamedist = distance
                
                # Don't process for the same ID more than once.
                if idMap.has_key(id):
                  continue
                  
                # Check to see if the item's release year is in the future, if so penalize.
                if imdbYear > datetime.datetime.now().year:
                  Log(imdbName + ' penalizing for future release date')
                  scorePenalty += 25
              
                # Check to see if the hinted year is different from imdb's year, if so penalize.
                elif media.year and imdbYear and int(media.year) != int(imdbYear): 
                  Log(imdbName + ' penalizing for hint year and imdb year being different')
                  yearDiff = abs(int(media.year)-(int(imdbYear)))
                  if yearDiff == 1:
                    scorePenalty += 5
                  elif yearDiff == 2:
                    scorePenalty += 10
                  else:
                    scorePenalty += 15
                    
                # Bonus (or negatively penalize) for year match.
                elif media.year and imdbYear and int(media.year) != int(imdbYear): 
                  scorePenalty += -5
                
                # It's a video game, run away!
                if title.count('(VG)') > 0:
                  break
                  
                # It's a TV series, don't use it.
                if title.count('(TV series)') > 0:
                  Log(imdbName + ' penalizing for TV series')
                  scorePenalty += 6
              
                # Sanity check to make sure we have SOME common substring.
                longestCommonSubstring = len(Util.LongestCommonSubstring(media.name.lower(), imdbName.lower()))
                
                # If we don't have at least 10% in common, then penalize below the 80 point threshold
                if (float(longestCommonSubstring) / len(media.name)) < .15: 
                  scorePenalty += 25
                
                # Finally, add the result.
                idMap[id] = True
                results.Append(MetadataSearchResult(id = id, name  = imdbName, year = imdbYear, lang  = lang, score = score - (scorePenalty + subsequentSearchPenalty)))
              except:
                Log('Exception processing IMDB Result')
                pass
           
            # Each search entry is worth less, but we subtract even if we don't use the entry...might need some thought.
            score = score - 4 
    ## end giant google block
      
    results.Sort('score', descending=True)
    
    # Finally, de-dupe the results.
    toWhack = []
    resultMap = {}
    for result in results:
      if not resultMap.has_key(result.id):
        resultMap[result.id] = True
      else:
        toWhack.append(result)
        
    for dupe in toWhack:
      results.Remove(dupe)

    # Make sure we're using the closest names.
    for result in results:
      result.name = bestNameMap[result.id]
      
  def update(self, metadata, media, lang):

    # Set the title. FIXME, this won't work after a queued restart.
    if media:
      metadata.title = media.title

    # Hit our repository.
    guid = re.findall('tt([0-9]+)', metadata.guid)[0]
    url = '%s/movies/%s/%s.xml' % (FREEBASE_URL, guid[-2:], guid)

    try:
      movie = XML.ElementFromURL(url)

      # Runtime.
      if int(movie.get('runtime')) > 0:
        metadata.duration = int(movie.get('runtime')) * 60 * 1000

      # Genres.
      metadata.genres.clear()
      genreMap = {}
      
      for genre in movie.xpath('genre'):
        id = genre.get('id')
        genreLang = genre.get('lang')
        genreName = genre.get('genre')
        
        if not genreMap.has_key(id) and genreLang in ('en', lang):
          genreMap[id] = [genreLang, genreName]
          
        elif genreMap.has_key(id) and genreLang == lang:
          genreMap[id] = [genreLang, genreName]
        
      keys = genreMap.keys()
      keys.sort()
      for id in keys:
        metadata.genres.add(genreMap[id][1])

      # Directors.
      metadata.directors.clear()
      for director in movie.xpath('director'):
        metadata.directors.add(director.get('name'))
        
      # Writers.
      metadata.writers.clear()
      for writer in movie.xpath('writer'):
        metadata.writers.add(writer.get('name'))
        
      # Actors.
      metadata.roles.clear()
      for movie_role in movie.xpath('actor'):
        role = metadata.roles.new()
        if movie_role.get('role'):
          role.role = movie_role.get('role')
        #role.photo = headshot_url
        role.actor = movie_role.get('name')
          
      # Studio
      if movie.get('company'):
        metadata.studio = movie.get('company')
        
      # Tagline.
      if len(movie.get('tagline')) > 0:
        metadata.tagline = movie.get('tagline')
        
      # Content rating.
      if movie.get('content_rating'):
        metadata.content_rating = movie.get('content_rating')
     
      # Release date.
      if len(movie.get('originally_available_at')) > 0:
        elements = movie.get('originally_available_at').split('-')
        if len(elements) >= 1 and len(elements[0]) == 4:
          metadata.year = int(elements[0])

        if len(elements) == 3:
          metadata.originally_available_at = Datetime.ParseDate(movie.get('originally_available_at')).date()
      
    except:
      print "Error obtaining Plex movie data for", guid

    m = re.search('(tt[0-9]+)', metadata.guid)
    if m and not metadata.year:
      id = m.groups(1)[0]
      (title, year) = self.findById(id)
      metadata.year = year


  def findById(self, id):
    jsonObj = self.getGoogleResults(GOOGLE_JSON_URL % (self.getPublicIP(), id))
    
    try:
      (title, year) = self.parseTitle(jsonObj[0]['titleNoFormatting'])
      return (title, year)
    except:
      pass
    
    return (None, None)

  def parseTitle(self, title):
    # Parse out title, year, and extra.
    titleRx = '(.*) \((TV )?([0-9]+)(/.*)?\).*'
    m = re.match(titleRx, title)
    if m:
      # A bit more processing for the name.
      imdbName = self.cleanupName(m.groups()[0])
      imdbYear = int(m.groups()[2])
      return (imdbName, imdbYear)
      
    longTitleRx = '(.*\.\.\.)'
    m = re.match(longTitleRx, title)
    if m:
      imdbName = self.cleanupName(m.groups(1)[0])
      return (imdbName, None)
    
    return (None, None)
    
  def cleanupName(self, s):
    imdbName = re.sub('^[iI][mM][dD][bB][ ]*:[ ]*', '', s)
    imdbName = re.sub('^details - ', '', imdbName)
    imdbName = re.sub('(.*:: )+', '', imdbName)
    imdbName = HTML.ElementFromString(imdbName).text
    
    if imdbName:
      if imdbName[0] == '"' and imdbName[-1] == '"':
        imdbName = imdbName[1:-1]
      return imdbName
    
    return None
    
