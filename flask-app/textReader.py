from geopy.geocoders import Nominatim
import nltk
import pandas as pd
import numpy as np
import spacy
from datetime import datetime
import pycountry
import locationtagger
import re
import roman
import datefinder
import rapidfuzz
from rapidfuzz import process
import os

# def fuzzy_match...

OCR_OUTPUT = "ocr_output"

def get_best_match(term, spec_list, threshold=80):
    match, score, _ = process.extractOne(term, spec_list)
    if score >= threshold:
        #print(f"Trying to match '{term}' | Best match: '{match}' (score: {score})!")
        return match, score
    else:
        #print(f"Low confidence genus match for '{term}': matched to '{match}' ({score})!")
        return term, score


def load_spec_vocab(file_path):
    with open(file_path, 'r') as f:
        lines = f.readlines()
    spec_list = [line.strip() for line in lines if line.strip()]
    return spec_list

def get_ngrams(words, max_n=5): # get ngrams from a list of words
    # used for fuzzy matching
    #why ngram? -> many countries, states, counties are made of Multiple words
    ngrams = []
    for n in range(1, max_n + 1):
        for i in range(len(words) - n + 1):
            ngram = " ".join(words[i:i + n])
            ngrams.append(ngram)
    return ngrams

def get_best_match_from_ngrams(ngrams, vocab_list, threshold=80):
    best_match, best_score = None, 0
    for ngram in ngrams:
        match, score = get_best_match(ngram, vocab_list, threshold=80)
        if score > best_score:
            best_match, best_score = match, score
    return (best_match, best_score) if best_score >= threshold else (None, 0)

def is_valid_date(date_str, format):
    try:
        datetime.strptime(date_str, format)
        return True
    except ValueError:
        return False

def split_date(date_str):
    day = month = year = ""
    date_list = [date_str]

    if re.search(r"\.", date_str):
        date_list = date_str.split(".")
    elif re.search(",", date_str):
        date_list = date_str.split(",")
    elif re.search("/", date_str):
        date_list = date_str.split("/")
    elif re.search("-", date_str):
        date_list = date_str.split("-")
    elif re.search(" ", date_str):
        date_list = date_str.split(" ")

    if len(date_list) == 3:
        day = date_list[0] + "/"
        month = date_list[1] + "/"
        year = date_list[2]
    elif len(date_list) == 2:
        month = date_list[0] + "/"
        year = date_list[1]
    elif len(date_list) == 1:
        year = date_list[0]
        if len(date_list[0]) == 3 and date_list[0][0] == "'":
            year = date_list[0].replace("'", "19")

    if (len(date_list) >= 2) and re.search("i|ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii", month):
        month = month[:-1]  # Get rid of slash
        numeral_List = re.findall("i|ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii", month)
        roman_numeral = "".join(numeral_List)
        month = str(roman.fromRoman(roman_numeral.upper())) + "/"
    elif (len(date_list) >= 2) and re.search("[^a-zA-Z]", month):
        month = month[:-1]  # Get rid of slash
        try:
            datetime_object = datetime.strptime(month, "%B")  # Uses the full month name format
        except ValueError:
            try:
                datetime_object = datetime.strptime(month, "%b")  # Uses the abbreviated month name format
            except ValueError:
                return None  # Return None for invalid month names
        month = datetime_object.month + "/"

    date_string = f"{month}{day}{year}"
    return date_string


# essential entity models downloads
nltk.download('punkt_tab')
nltk.download('averaged_perceptron_tagger_eng')
nltk.download('maxent_ne_chunker_tab')


#def categorySort():
if __name__ == "__main__":
    ### BASIC STEP BY STEP:
        # 1. Split OCR output (which I assume is just one big string of \n delimited text
        # 2. Separate said words into categories: parsedList[]
        #     Categories:
        #       [0]CatalogNumber	[1]Specimen_voucher<MGCL #>	[2]Family	[3]Genus<Phoebis>	[4]Species<sennae>	[5]Subspecies<sennae>	[6]Sex<female/male>
        #       [7]Country	[8]State	[9]County	[10]Locality name	[11]Elevation min	[12]Elevation max	[13]Elevation unit	[14]Collectors	[15]Latitude	[16]Longitude
        #       [17]Georeferencing source	[18]Georeferencing precision	[19]Questionable label data [20]Do not publish
        #       [21]Collecting event start	[22]Collecting event end	[23]Date verbatim           *** NOTE: Collecting event start/end are the same, in MM/DD/YYYY format
        #       [24]Remarks public	[25]Remarks private	    [26]Cataloged date***can collect ourselves	[27]Cataloger First [28]Cataloger last***can collect ourselves
        #       [29]Prep type 1 [30]Prep count 1	[31]Prep type 2	    [32]Prep number 2	[33]Prep type 3 [34]Prep number 3	[35]Other record number
        #       [36]Other record source     [37]publication     [38]publication
        # 3. Input parsed list into a CSV format, where the first line is the label names and then the rest of it is the information
        # Consistencies:
        #   - The species name will always be first
        #   - Date will always have a year and month - date is tricky, but we can say that if there's 2 periods/commas, there's a day -
        #   if not, and there's only one (or only one space), it's a day
        #   - Labels 24 - 39 are not part of the labels!


### CODE START ###
    # data is the template list of metadata attributes; there'll be a list for each image
    # Category[0]: CatalogNumber can be filled in off the top (#########)
    data = [["#########", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN"]]

    # Create the pandas DataFrame: df
    # df will contain the parsed metadata for each image
    df = pd.DataFrame(data, columns=['CatalogNumber', 'Specimen_voucher', 'Family', 'Genus', 'Species', 'Subspecies', 'Sex', 'Country', 'State', 'County', 'Locality name', 'Elevation min', 'Elevation max', 'Elevation unit', 'Collectors', 'Latitude', 'Longitude', 'Georeferencing source', 'Georeferencing precision', 'Questionable label data', 'Do not publish', 'Collecting event start', 'Collecting event end', 'Date verbatim', 'Remarks public', 'Remarks private', 'Cataloged date', 'Cataloger First', 'Cataloger last', 'Prep type 1', 'Prep count 1', 'Prep type 2', 'Prep number 2', 'Prep type 3', 'Prep number 3', 'Other record number', 'Other record source', 'publication', 'publication1'])
    print("df", df)
    currentIndex = 0  # Refers to the current ocr output we're parsing (0 - (n-1)) where n is the number of photos uploaded

    ### START READING FROM THE OCR OUTPUT FILE (data.csv)
    with open(os.path.join(OCR_OUTPUT, "data.csv"), 'r') as file:
        next(file)  # Skip header (contains df category names)
        for line in file:
            df.loc[len(df)] = [None] * len(df.columns)
            print(line)
            listOfStrings = line.strip().split('"')
            for x in listOfStrings:
                if x == '' or x == ',':
                    listOfStrings.remove(x)
            print("List of strings: ", listOfStrings)

            # Default values of the df
            df.loc[currentIndex] = ["#########", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN",
                 "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN",
                 "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN"]

            # The order that the categories are filled in is, at first, determined by the order the text is parsed from the photo
            # Some items, (genus, species, and subspecies) always come first
            # Categories 3 - 6: (family--not often included...), Genus, Species, and Subspecies
            for x in range(3, 6):
                print("Current index: ", x)
                if listOfStrings[0] != "UF" and listOfStrings[0] != "FLMNH":
                    #print("List of strings[0]: ", listOfStrings[0])
                    word = listOfStrings[0]
                    old_word = listOfStrings[0]
                    ratio = 0

                    if " " in listOfStrings[0]:
                        twoWordList = word.split(" ")
                        word = twoWordList[0]
                        old_word = twoWordList[0]
                        del listOfStrings[0]
                        listOfStrings.insert(0, twoWordList[0])
                        listOfStrings.insert(1, twoWordList[1])

                    #genus
                    if (x == 3): #, 4, 5, etc:  # separate the genus from the species, subspecies
                        #genus dictionaries/
                        word, ratio = get_best_match(word, load_spec_vocab("dictionaries/genusDict.txt"))
                        # change estimate = ratio
                    elif (x == 4):
                        #species
                        word, ratio = get_best_match(word, load_spec_vocab("dictionaries/speciesDict.txt"))
                        # change estimate = ratio
                    elif (x == 5):
                        #subspecies
                        word, ratio = get_best_match(word, load_spec_vocab("dictionaries/subspeciesDict.txt"))
                        # change estimate = ratio

                    vagueWord, broadRatio = get_best_match(word, load_spec_vocab("dictionaries/vagueDict.txt"))
                    if broadRatio >= ratio:
                        word = vagueWord
                        # change estimate = broadRatio
                    print(f"Replaced '{old_word}' with '{word}'")

                    df.iloc[currentIndex, x] = word
                    listOfStrings.remove(old_word)


            # Category[6]: Sex Symbol
            if chr(0x2640) in listOfStrings:    # FEMALE
                df.loc[currentIndex, 'Sex'] = "female"
                listOfStrings.remove(chr(0x2640))
            elif chr(0x2642) in listOfStrings:  # MALE
                df.loc[currentIndex, 'Sex'] = "male"
                listOfStrings.remove(chr(0x2642))

            ### Category[1]: Specimen Voucher
            # First check if UF and FLMNH are in there somewhere
            for word in listOfStrings:
                if re.search(r"UF", word) is not None:
                    listOfStrings.remove(word)

            for word in listOfStrings:
                if re.search(r"FLMNH", word) is not None:  # Get rid of UF or FLMNH
                    listOfStrings.remove(word)

            # Split the string (delim will allow us to reincorporate it into list form in the proper order later)
            delim = " | "
            joinedStrings = delim.join(listOfStrings)
            print("New and improved joined string: ", joinedStrings)


            voucher = "NaN"
            x = re.search(r"\bMGCL [0-9]{7}", joinedStrings)
            if x.group() in joinedStrings:
                voucher = x.group()
                # Update list of strings (we need to remove the specimen voucher)
                listOfStrings = listOfStrings.remove(x.group())
                joinedStrings = joinedStrings.replace(x.group(), "")  # REMOVE FROM BIG STRING

            df.loc[currentIndex, 'Specimen_voucher'] = voucher


            ### Extracting Location Entities: Categories[7 - 10] ###
            placeEntity = locationtagger.find_locations(text=joinedStrings)

            # split all words into ngrams to test against the dictionaries
            words = [t for t in joinedStrings.split() if len(t) > 2]
            ngrams = get_ngrams(words, 3) #heres the thing... so few have 5 words

            # load dictionaries
            countryList = load_spec_vocab("dictionaries/countryDict.txt")
            stateList = load_spec_vocab("dictionaries/stateDict.txt")
            countyList = load_spec_vocab("dictionaries/countyDict.txt")

            ### Getting all countries
            print("The countries in text : ")
            print(placeEntity.countries)
            df.loc[currentIndex, 'Country'] = ", ".join(placeEntity.countries)
            joinedStrings = joinedStrings.replace(df.loc[currentIndex, 'Country'], "")  # REMOVE FROM BIG STRING
            if not placeEntity.countries:
                # if location tagger doesn't find a country, try to find one using fuzzy matching
                best_match, score = get_best_match_from_ngrams(ngrams, countryList)
                if best_match:
                    # change the corresponding estimate = score
                    df.loc[currentIndex, 'Country'] = best_match
                    joinedStrings = joinedStrings.replace(best_match, "")  # REMOVE FROM BIG STRING
                else:
                    print("No country found")

            ### Getting all states
            print("The states in text : ")
            print(placeEntity.regions)
            df.loc[currentIndex, 'State'] = ", ".join(placeEntity.regions)
            joinedStrings = joinedStrings.replace(df.loc[currentIndex, 'State'], "")  # REMOVE FROM BIG STRING
            if not placeEntity.regions:
                best_match, score = get_best_match_from_ngrams(ngrams, stateList)
                if best_match:
                    # change the corresponding estimate = score
                    df.loc[currentIndex, 'State'] = best_match
                    joinedStrings = joinedStrings.replace(best_match, "")  # REMOVE FROM BIG STRING
                else:
                    print("No state found")

            ### Getting all counties
            best_match, score = get_best_match_from_ngrams(ngrams, countyList)
            # change the corresponding estimate = score
            df.loc[currentIndex, 'County'] = best_match
            if not best_match:
                df.loc[currentIndex, 'County'] = 'NaN'
                # use city ?

            # Getting all cities
            print("The cities in text : ")
            print(placeEntity.cities)


            ### CLEANING SOME STUFF UP BEFORE NUMBER CALCULATIONS
            # Remove collection information 19XX-XX stuff from string
            joinedStrings = re.sub("[0-9]{4}-[0-9]+", "", joinedStrings)


            ### Category[12]: Elevation Max (will always have the unit attached to it so this is the reliable one)
            # UNITS: m, km, ft, mi, yd
            x = re.search(r"\d+ ?[dfikmty]*[.']?", joinedStrings)
            print("Elevation:", x.group())
            if x.group() in joinedStrings:
                unit = re.search(r"[a-zA-Z]+", x.group())
                if unit:
                    print("UNIT: ", unit.group())
                    df.loc[currentIndex, 'Elevation unit'] = unit.group()
                    df.loc[currentIndex, 'Elevation max'] = re.sub(r"[a-zA-Z]+", "", x.group())
                else:
                    df.loc[currentIndex, 'Elevation max'] = x.group()
                joinedStrings = re.sub(x.group(), "", joinedStrings)


            ### NOW BEGINS THE DATE SAGA ###
            print("\nJoined strings: ", joinedStrings)

            datefinder_output = []  #
            datefinder.find_dates(joinedStrings)

            if not datefinder_output:
                dates_found = []
                ### START CHECKING FOR THE COMMON DATE OUTPUTS
                # DD.MM.YYYY | DD,MM,YYYY | DD/MM/YYYY | DD-MM-YYYY   OR   MM.DD.YYYY | MM,DD,YYYY | MM/DD/YYYY | MM-DD-YYYY
                if re.search(r"\d{1,2}[\s.,/-]{1}\d{2}[\s.,/-]{1}\d{4}", joinedStrings) is not None:
                    print("It's a DD/MM/YYYY format!")
                    x = re.search(r"\d{1,2}[\s.,/-]{1}\d{2}[\s.,/-]{1}\d{4}", joinedStrings)
                    dates_found = x.group()
                # Roman numerals format
                # DD.MM.YYYY where MM = roman numerals
                elif re.search(r"\d{1,2}[.,\s]*(?:i|ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii)*[.,\s]*\d{4}", joinedStrings):
                    print("It's DD.MM.YYYY roman numerals format!")
                    x = re.search(r"\d{1,2}[.,\s]*(?:i|ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii)*[.,\s]*\d{4}", joinedStrings)
                    dates_found = x.group()
                # DD MM YYYY where MM = date name (abbreviate or otherwise).
                elif re.search("(?:\d{1,2} )?[.,\s]*[a-zA-Z]+[.,\s]*\d{2,4}", joinedStrings):
                    print("It's a DD MonthName YYYY format!")
                    if re.search(r"(?:\d{1,2} )?(?:jan|JAN|feb|FEB|mar|MAR|apr|APR|may|MAY|jun|JUN|jul|JUL|aug|AUG|sept|SEPT|oct|OCT|nov|NOV|dec|DEC|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept|Oct|Nov|Dec)*[., ]{1,3}\d{4};*", joinedStrings):
                        print("Abbreviated Date")
                        x = re.search(r"(?:\d{1,2} )?(?:jan|JAN|feb|FEB|mar|MAR|apr|APR|may|MAY|jun|JUN|jul|JUL|aug|AUG|sept|SEPT|oct|OCT|nov|NOV|dec|DEC|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept|Oct|Nov|Dec)*[., ]{1,3}\d{4};*", joinedStrings)
                        dates_found = x.group()
                    elif re.search("(?:\d{1,2} )?(?:January|February|March|April|May|June|July|August|September|October|November|December|JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)*[., ]{1,3}\d{4};*", joinedStrings):
                        print("Non-abbreviated Date")
                        x = re.search("(?:\d{1,2} )?(?:January|February|March|April|May|June|July|August|September|October|November|December|JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)*[., ]{1,3}\d{4};*", joinedStrings)
                        dates_found = x.group()
                # YYYY   OR   'YY
                elif re.search("\d{4};?(?![a-zA-Z-])", joinedStrings) is not None:
                    print("It's a YYYY format!")
                    x = re.search("\d{4};?(?![a-zA-Z-])", joinedStrings)
                    dates_found = x.group()
                elif re.search("'?\d{2};?(?![a-zA-Z-])", joinedStrings) is not None:
                    print("It's a 'YY format!")
                    x = re.search("\d{2};?(?![a-zA-Z-])", joinedStrings)
                    dates_found = x.group()
                else:
                    dates_found.append("NaN")

                print("Preliminary dates found: ", dates_found)
                df.loc[currentIndex, 'Date verbatim'] = dates_found

                # Categories[21 - 22] (they're the same)
                proper_date = split_date(dates_found)
                print("Proper date: ", proper_date)
                df.loc[currentIndex, 'Collecting event start'] = proper_date
                df.loc[currentIndex, 'Collecting event end'] = proper_date

                joinedStrings = joinedStrings.replace(dates_found, "")  # REMOVE DATE FROM BIG STRING
            else:
                print("Dates found: ")
                for dates in datefinder_output:
                    print(dates)
                    # Categories[21 - 22]
                    ### NOTE: If we use datefinder, we can't transcribe it verbatim
                    df.loc[currentIndex, 'Collecting event start'] = dates.strftime('%m/%d/%Y')
                    df.loc[currentIndex, 'Collecting event end'] = dates.strftime('%m/%d/%Y')
                    break


            ### Category[14]: Collector
            # Thought process: If we isolate strings with the ampersand, that's closer than nothing
            ### HARD RESET OF STRING: (We're also gonna remove the sta. and Acc.)
            joinedStrings = re.sub(r"sta\.", "", joinedStrings)
            joinedStrings = re.sub(r"Acc\.", "", joinedStrings)
            listOfStrings = joinedStrings.split(" | ")
            listOfStrings = list(filter(None, listOfStrings))  # Removes empty strings
            print("\nPost date strings: ", listOfStrings)

            collectors = ""
            for string in listOfStrings:
                if "&" in string:
                    if collectors == "":
                        collectors += string
                    else:
                        collectors += " " + string
                    joinedStrings = joinedStrings.replace(string, "")

            if collectors == "":
                collectors = "NaN"
            else:
                # Remove extraneous semicolons, space or not
                collectors = re.sub(r"(;\s)|;", "", collectors)

            df.loc[currentIndex, 'Collectors'] = collectors


            ### Category[26]: Date cataloged (current date at time of program running)
            df.loc[currentIndex, 'Cataloged date'] = datetime.now().strftime("%m-%d-%Y")


            ### OKAY NOW PRINT REMAINING STRING ###
            listOfStrings = joinedStrings.split(" | ")
            listOfStrings = list(filter(None, listOfStrings))  # Removes empty strings
            print("Updated listOfStrings: ", listOfStrings)

            currentIndex += 1   # Go to next line

    ### FINAL PRINT OF DATAFRAME
    df = df.iloc[:-1]   # Remove extraneous last row
    pd.set_option('display.max_columns', None)
    print("\nUpdated df:\n", df)
    df.to_csv(os.path.join(OCR_OUTPUT, "parsed.csv"), index=False)