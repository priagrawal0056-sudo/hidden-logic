"""Narrow written/spoken equivalence without fuzzy transcript acceptance."""
import re

# These have unambiguous expansions. Ambiguous 's / 'd forms are not generalized.
EXPANSIONS = {
    "don't":"donot", "doesn't":"doesnot", "didn't":"didnot",
    "isn't":"isnot", "aren't":"arenot", "wasn't":"wasnot", "weren't":"werenot",
    "can't":"cannot", "couldn't":"couldnot", "won't":"willnot", "wouldn't":"wouldnot",
    "shouldn't":"shouldnot", "haven't":"havenot", "hasn't":"hasnot", "hadn't":"hadnot",
    "i'm":"iam", "you're":"youare", "we're":"weare", "they're":"theyare",
    "i've":"ihave", "you've":"youhave", "we've":"wehave", "they've":"theyhave",
    "i'll":"iwill", "you'll":"youwill", "we'll":"wewill", "they'll":"theywill",
}


def spoken_keys(parts):
    """One key per original timing group; preserve measured boundary ownership."""
    tokens=[]
    result=['' for _ in parts]
    for group,part in enumerate(parts):
        for token in part.replace('’', "'").lower().split():
            tokens.append((group, re.sub(r"^[^a-z0-9]+|[^a-z0-9']+$", '', token)))
    for i,(group,token) in enumerate(tokens):
        following=tokens[i+1][1] if i+1<len(tokens) else ''
        # 'Why is there' is the observed recognizer expansion; do not equate
        # arbitrary ambiguous possessives or 'has' with 'is'.
        key='whyis' if token=="why's" and following=='there' else EXPANSIONS.get(token,token)
        result[group]+=re.sub(r'[^a-z0-9]','',key)
    return result


def alignment_keys(expected, actual):
    # Preserve exact spelling/grouping equivalence first (e.g. doesn / t,
    # or DNS vs D / N / S). Only use expansion when that strict match fails.
    clean=lambda part: re.sub(r'[^a-z0-9]','',part.lower())
    left=[clean(part) for part in expected];right=[clean(part) for part in actual]
    if ''.join(left)==''.join(right):
        return left,right
    return spoken_keys(expected),spoken_keys(actual)
