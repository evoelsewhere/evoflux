export interface MemoryCard { id: number; pair: number; revealed: boolean; matched: boolean }
export interface MemoryState { cards: MemoryCard[]; openCards: number[]; pairsFound: number; status: 'playing' | 'won' }

export function createMemoryState(random: () => number = Math.random): MemoryState {
  const cards = Array.from({ length: 8 }, (_, pair) => [pair, pair]).flat().map((pair, id) => ({ id, pair, revealed: false, matched: false }))
  for (let index = cards.length - 1; index > 0; index -= 1) {
    const other = Math.floor(random() * (index + 1))
    ;[cards[index], cards[other]] = [cards[other], cards[index]]
  }
  return { cards, openCards: [], pairsFound: 0, status: 'playing' }
}

export function flipMemoryCard(state: MemoryState, index: number): MemoryState {
  if (state.status !== 'playing' || state.openCards.length >= 2 || !state.cards[index] || state.cards[index].revealed) return state
  const card = state.cards[index]
  if (card.matched) return state
  const cards = state.cards.map((item, cardIndex) => cardIndex === index ? { ...item, revealed: true } : item)
  const openCards = [...state.openCards, index]
  if (openCards.length < 2) return { ...state, cards, openCards }
  const [first, second] = openCards
  if (cards[first].pair !== cards[second].pair) return { ...state, cards, openCards }
  const matchedCards = cards.map((item, cardIndex) => cardIndex === first || cardIndex === second ? { ...item, matched: true } : item)
  const pairsFound = state.pairsFound + 1
  return { cards: matchedCards, openCards: [], pairsFound, status: pairsFound === 8 ? 'won' : 'playing' }
}

export function resolveMemoryMismatch(state: MemoryState): MemoryState {
  if (state.openCards.length !== 2 || state.cards[state.openCards[0]].pair === state.cards[state.openCards[1]].pair) return state
  const cards = state.cards.map((card, index) => state.openCards.includes(index) ? { ...card, revealed: false } : card)
  return { ...state, cards, openCards: [] }
}
