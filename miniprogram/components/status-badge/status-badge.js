Component({
  properties: {
    type: {
      type: String,
      value: 'info', // success | warning | danger | info
    },
    text: {
      type: String,
      value: '',
    },
  },
})
