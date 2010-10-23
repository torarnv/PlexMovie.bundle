import datetime, re, time, unicodedata

# [might want to look into language/country stuff at some point] 
# param info here: http://code.google.com/apis/ajaxsearch/documentation/reference.html
#
GOOGLE_JSON_URL = 'http://ajax.googleapis.com/ajax/services/search/web?v=1.0&rsz=large&q=%s'   
FREEBASE_URL    = 'http://freebase.plexapp.com'

def Start():
  HTTP.CacheTime = CACHE_1HOUR * 4
  
class PlexMovieAgent(Agent.Movies):
  name = 'Freebase'
  languages = [Locale.Language.English, 'sv', 'fr', 'es', 'nl', 'de', 'it']
  
  def getGoogleResult(self, url):
    res = JSON.ObjectFromURL(url)
    if res['responseStatus'] != 200:
      res = JSON.ObjectFromURL(url, cacheTime=0)
    time.sleep(0.5)
    return res
  
  def search(self, results, media, lang):
    
    # See if we're being passed a raw ID.
    if media.guid or re.match('t*[0-9]{7}', media.name):
      theGuid = media.guid or media.name
      if not theGuid.startswith('tt'):
        theGuid = 'tt' + theGuid
      
      # Add a result for the id found in the passed in guid hint.
      (title, year) = self.findById(theGuid)
      if title is not None:
        results.Append(MetadataSearchResult(id=theGuid, name=title, year=year, lang=lang, score=100))
          
    if media.year:
      searchYear = ' (' + str(media.year) + ')'
    else:
      searchYear = ''
    
    normalizedName = String.StripDiacritics(media.name)
    GOOGLE_JSON_QUOTES = GOOGLE_JSON_URL % String.Quote('"' + normalizedName + searchYear + '"', usePlus=True) + '+site:imdb.com'
    GOOGLE_JSON_NOQUOTES = GOOGLE_JSON_URL % String.Quote(normalizedName + searchYear, usePlus=True) + '+site:imdb.com'
    GOOGLE_JSON_NOSITE = GOOGLE_JSON_URL % String.Quote(normalizedName + searchYear, usePlus=True) + '+imdb.com'
    
    subsequentSearchPenalty = 0
    idMap = {}
    bestNameMap = {}
    bestNameDist = 1000
    
    for s in [GOOGLE_JSON_QUOTES, GOOGLE_JSON_NOQUOTES, GOOGLE_JSON_NOSITE]:
      if s == GOOGLE_JSON_QUOTES and (media.name.count(' ') == 0 or media.name.count('&') > 0 or media.name.count(' and ') > 0):
        # no reason to run this test, plus it screwed up some searches
        continue 
        
      subsequentSearchPenalty += 1

       # Check to see if we need to bother running the subsequent searches
      if len(results) <= 3:
        score = 99
        
        # Make sure we have results and normalize them.
        hasResults = False
        try:
          if s.count('googleapis.com') > 0:
            jsonObj = self.getGoogleResult(s)
            if jsonObj['responseData'] != None:
              jsonObj = jsonObj['responseData']['results']
              if len(jsonObj) > 0:
                hasResults = True
                urlKey = 'unescapedUrl'
                titleKey = 'titleNoFormatting'
        except:
          Log("Exception processing search engine results.")
          pass
          
        # Now walk through the results.    
        if hasResults:
          for r in jsonObj:
            
            # Get data.
            url = r[urlKey]
            title = r[titleKey]

            # Parse the name and year.
            imdbName, imdbYear = self.parseTitle(title)
            if not imdbName:
              # Doesn't match, let's skip it.
              Log("Skipping strange title: " + title + " with URL " + url)
              continue
            else:
              Log("Using [%s] derived from [%s] (url=%s)" % (imdbName, title, url))
              
            scorePenalty = 0
            url = r[urlKey].lower().replace('us.vdc','www').replace('title?','title/tt') #massage some of the weird url's google has
            if url[-1:] == '/':
              url = url[:-1]
      
            splitUrl = url.split('/')
      
            if len(splitUrl) == 6 and splitUrl[-2].startswith('tt'):
              
              # This is the case where it is not just a link to the main imdb title page, but to a subpage. 
              # In some odd cases, google is a bit off so let's include these with lower scores "just in case".
              #
              scorePenalty = 10
              del splitUrl[-1]
      
            if len(splitUrl) > 5 and splitUrl[-1].startswith('tt'):
              while len(splitUrl) > 5:
                del splitUrl[-2]
              scorePenalty += 5

            if len(splitUrl) == 5 and splitUrl[-1].startswith('tt'):
              id = splitUrl[-1]
              if id.count('+') > 0:
                # Penalizing for abnormal tt link.
                scorePenalty += 10
              try:
                
                # Keep the closest name around.
                distance = Util.LevenshteinDistance(media.name, imdbName)
                if not bestNameMap.has_key(id) or distance < bestNameDist:
                  bestNameMap[id] = imdbName
                  bestNameDist = distance
                
                # Don't process for the same ID more than once.
                if idMap.has_key(id):
                  continue
                  
                idMap[id] = True
                
                # Check to see if the item's release year is in the future, if so penalize.
                if imdbYear > datetime.datetime.now().year:
                  Log(imdbName + ' penalizing for future release date')
                  scorePenalty += 25
              
                # Check to see if the hinted year is different from imdb's year, if so penalize.
                elif media.year and int(media.year) != int(imdbYear): 
                  Log(imdbName + ' penalizing for hint year and imdb year being different')
                  yearDiff = abs(int(media.year)-(int(imdbYear)))
                  if yearDiff == 1:
                    scorePenalty += 5
                  elif yearDiff == 2:
                    scorePenalty += 10
                  else:
                    scorePenalty += 15
                    
                # Bonus (or negatively penalize) for year match.
                elif media.year and int(media.year) != int(imdbYear): 
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
                results.Append(MetadataSearchResult(id = id, name  = imdbName, year = imdbYear, lang  = lang, score = score - (scorePenalty + subsequentSearchPenalty)))
              except:
                Log('Exception processing IMDB Result')
                pass
           
            # Each search entry is worth less, but we subtract even if we don't use the entry...might need some thought.
            score = score - 4 
      
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

    # FIXME, this is dumb, we already know the title.
    m = re.search('(tt[0-9]+)', metadata.guid)
    if m:
      id = m.groups(1)[0]
      (title, year) = self.findById(id)
      metadata.year = year

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

  def findById(self, id):
    jsonObj = self.getGoogleResult(GOOGLE_JSON_URL % id)
    if jsonObj['responseData'] != None:
      jsonObj = jsonObj['responseData']['results']
    
    try:  
      (title, year) = self.parseTitle(jsonObj[0]['titleNoFormatting'])
      return (title, year)
    except:
      pass
    
    return (None, None)

  def parseTitle(self, title):
    # Parse out title, year, and extra.
    titleRx = '(.*) \(([0-9]+)(/.*)?\).*'
    m = re.match(titleRx, title)
    if m:
      # A bit more processing for the name.
      imdbName = self.cleanupName(m.groups(1)[0])
      imdbYear = int(m.groups(1)[1])
      return (imdbName, imdbYear)
      
    longTitleRx = '(.*\.\.\.)'
    m = re.match(longTitleRx, title)
    if m:
      imdbName = self.cleanupName(m.groups(1)[0])
      return (imdbName, None)
    
    return (None, None)
    
  def cleanupName(self, s):
    imdbName = re.sub('^[iI][mM][dD][bB][ ]*:[ ]*', '', s)
    imdbName = re.sub('^details - ', '', s)
    imdbName = re.sub('(.*:: )+', '', s)
    imdbName = HTML.ElementFromString(imdbName).text
    
    if imdbName:
      if imdbName[0] == '"' and imdbName[-1] == '"':
        imdbName = imdbName[1:-1]
      return imdbName
    
    return None
    