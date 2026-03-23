# fantasy-bb

## Open Slots Tool
I need a tool to help me with my fantasy baseball league draft.

Read the rules of the league here: https://www.cbssports.com/fantasy/baseball/games/free/rules

We run an American League Team only league.

Focus on the rules around what batter positions need to be drafted. Note how the rules have special positions that
are "either/or" for 2B/SS and 1B/3B. 

Also focus on the rules for position eligibility. The specifics are probably not important, but realize that if I am
thinking of drafting a player, I need to check the positions he is eligible for, and then check if I have any openings on
my partially filled roster to add that player in one of his eligible positions.

I would like a tool that would tell me what positions I currently have open on my roster. This is tricky because the players
I have can be arranged in different configurations that align with the roster rules, but may open up different positions.

Is this a problem that can be solved "analytically" or with some simple functionality in a spreadsheet, or can this only be
solved by more "brute force" methods of iterating through all of the possible roster configurations with the players I have
already drafted.

Let's first discuss the eligibility and roster rules and confirm we have the same understanding.

Then let's talk about how to solve the problem.

## Data Tool
Next we are going to build a draft day tool (app) and aggregate some data. 


First, we will scan through these depth charts and build a depth chart grid of teams and starting players for all of the AL teams.
https://www.cbssports.com/fantasy/baseball/depth-chart/

Retain any notes there about injuries, etc. These depth charts change, so it should be easy to refresh.

Then using the pages below, build up supporting data for each of the players. Hovering over a players name in the depth chart grid will reveal
further information.
https://sabr.app.box.com/s/y1prhc795jk8zvmelfd3jq7tl389y6cd
https://sabr.app.box.com/s/y1prhc795jk8zvmelfd3jq7tl389y6cd/file/2084259918153
https://www.cbssports.com/fantasy/baseball/rankings/roto/top300/AL/

Next to each player's name will be a checkbox. When checked, it will indicate the player has been drafted.

Below the depth chart grid will be a list of all remaining starters who haven't been drafted yet, in rank order.
